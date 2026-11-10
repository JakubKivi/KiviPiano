"""Local inference adapter for the official Google MT3 checkpoint."""

import functools
from pathlib import Path

import gin
import jax
import numpy as np
import seqio
import t5
import t5x
import tensorflow.compat.v2 as tf

import mt3
from mt3 import metrics_utils, models, network, note_sequences
from mt3 import preprocessors, spectrograms, vocabularies


class MT3InferenceModel:
    def __init__(self, checkpoint_dir: Path) -> None:
        self.inputs_length = 256
        self.outputs_length = 1024
        self.batch_size = 8
        self.sequence_length = {
            "inputs": self.inputs_length,
            "targets": self.outputs_length,
        }
        self.partitioner = t5x.partitioning.PjitPartitioner(num_partitions=1)
        self.spectrogram_config = spectrograms.SpectrogramConfig()
        self.codec = vocabularies.build_codec(
            vocab_config=vocabularies.VocabularyConfig(num_velocity_bins=1)
        )
        self.vocabulary = vocabularies.vocabulary_from_codec(self.codec)
        self.output_features = {
            "inputs": seqio.ContinuousFeature(dtype=tf.float32, rank=2),
            "targets": seqio.Feature(vocabulary=self.vocabulary),
        }

        # The gin configs ship inside the installed ``mt3`` package (the repo
        # clones to ``/opt/mt3``, so the package lives at ``/opt/mt3/mt3`` and
        # the configs at ``/opt/mt3/mt3/gin``). Resolve them from the package
        # location instead of hardcoding the clone path.
        mt3_gin_dir = Path(mt3.__file__).resolve().parent / "gin"
        gin_files = [
            str(mt3_gin_dir / "model.gin"),
            str(mt3_gin_dir / "mt3.gin"),
        ]
        gin_bindings = [
            "from __gin__ import dynamic_registration",
            "from mt3 import vocabularies",
            "VOCAB_CONFIG=@vocabularies.VocabularyConfig()",
            "vocabularies.VocabularyConfig.num_velocity_bins=1",
        ]
        with gin.unlock_config():
            gin.parse_config_files_and_bindings(
                gin_files, gin_bindings, finalize_config=False
            )

        model_config = gin.get_configurable(network.T5Config)()
        module = network.Transformer(config=model_config)
        self.model = models.ContinuousInputsEncoderDecoderModel(
            module=module,
            input_vocabulary=self.output_features["inputs"].vocabulary,
            output_vocabulary=self.output_features["targets"].vocabulary,
            optimizer_def=t5x.adafactor.Adafactor(
                decay_rate=0.8, step_offset=0
            ),
            input_depth=spectrograms.input_depth(self.spectrogram_config),
        )
        self._restore(checkpoint_dir)

    @property
    def input_shapes(self):
        return {
            "encoder_input_tokens": (self.batch_size, self.inputs_length),
            "decoder_input_tokens": (self.batch_size, self.outputs_length),
        }

    def _restore(self, checkpoint_dir: Path) -> None:
        initializer = t5x.utils.TrainStateInitializer(
            optimizer_def=self.model.optimizer_def,
            init_fn=self.model.get_initial_variables,
            input_shapes=self.input_shapes,
            partitioner=self.partitioner,
        )
        restore_config = t5x.utils.RestoreCheckpointConfig(
            path=str(checkpoint_dir), mode="specific", dtype="float32"
        )
        axes = initializer.train_state_axes
        self._predict_fn = self._get_predict_fn(axes)
        self._train_state = initializer.from_checkpoint_or_scratch(
            [restore_config], init_rng=jax.random.PRNGKey(0)
        )

    @functools.lru_cache()
    def _get_predict_fn(self, train_state_axes):
        def predict_fn(params, batch, _decode_rng):
            return self.model.predict_batch_with_aux(
                params, batch, decoder_params={"decode_rng": None}
            )

        return self.partitioner.partition(
            predict_fn,
            in_axis_resources=(
                train_state_axes.params,
                t5x.partitioning.PartitionSpec("data"),
                None,
            ),
            out_axis_resources=t5x.partitioning.PartitionSpec("data"),
        )

    def _predict_tokens(self, batch):
        prediction, _ = self._predict_fn(
            self._train_state.params, batch, jax.random.PRNGKey(0)
        )
        return self.vocabulary.decode_tf(prediction).numpy()

    def __call__(self, audio):
        frame_size = self.spectrogram_config.hop_width
        padding = [0, frame_size - len(audio) % frame_size]
        audio = np.pad(audio, padding, mode="constant")
        frames = spectrograms.split_audio(audio, self.spectrogram_config)
        frame_count = len(audio) // frame_size
        frame_times = (
            np.arange(frame_count)
            / self.spectrogram_config.frames_per_second
        )
        dataset = tf.data.Dataset.from_tensors(
            {"inputs": frames, "input_times": frame_times}
        )
        dataset = self._preprocess(dataset)
        model_dataset = self.model.FEATURE_CONVERTER_CLS(pack=False)(
            dataset, task_feature_lengths=self.sequence_length
        ).batch(self.batch_size)

        predictions = []
        token_batches = (
            tokens
            for batch in model_dataset.as_numpy_iterator()
            for tokens in self._predict_tokens(batch)
        )
        for example, tokens in zip(dataset.as_numpy_iterator(), token_batches):
            tokens = np.asarray(tokens, np.int32)
            eos = tokens == vocabularies.DECODED_EOS_ID
            if eos.any():
                tokens = tokens[: np.argmax(eos)]
            start_time = example["input_times"][0]
            start_time -= start_time % (1 / self.codec.steps_per_second)
            predictions.append(
                {
                    "est_tokens": tokens,
                    "start_time": start_time,
                    "raw_inputs": [],
                }
            )
        result = metrics_utils.event_predictions_to_ns(
            predictions,
            codec=self.codec,
            encoding_spec=note_sequences.NoteEncodingWithTiesSpec,
        )
        return result["est_ns"]

    def _preprocess(self, dataset):
        operations = [
            functools.partial(
                t5.data.preprocessors.split_tokens_to_inputs_length,
                sequence_length=self.sequence_length,
                output_features=self.output_features,
                feature_key="inputs",
                additional_feature_keys=["input_times"],
            ),
            preprocessors.add_dummy_targets,
            functools.partial(
                preprocessors.compute_spectrograms,
                spectrogram_config=self.spectrogram_config,
            ),
        ]
        for operation in operations:
            dataset = operation(dataset)
        return dataset
