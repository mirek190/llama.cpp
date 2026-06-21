# Output Multimodal Support in llama.cpp

`libomtd` is the output-side companion to `libmtmd`.

- `libmtmd`: input media -> embeddings -> language model
- `libomtd`: language model output or hidden states -> generated media

The first supported OMTD model is Higgs Audio v3 for local text-to-speech. Image
and video output modalities are reserved in the public API, but are not
implemented yet.

## Scope

OMTD is for generated outputs. It is not a replacement for MTMD and it does not
load `--mmproj` files.

Use:

- `--mmproj FILE` for MTMD input-media projectors
- `--omtd FILE` for OMTD output-media companion files

For Higgs Audio v3, the normal language model GGUF contains the Qwen3 text
backbone and the OMTD companion GGUF contains Higgs audio metadata, codebook
weights, RVQ weights, and DAC/BigVGAN vocoder weights.

## Current Pipeline

A typical OMTD audio pipeline is:

- Load the text backbone with normal llama.cpp model loading.
- Load an output-modality companion GGUF through OMTD.
- Run the model-specific output generator.
- Convert generated hidden states or codebook tokens through the companion
  model.
- Decode generated media data, such as RVQ + DAC/BigVGAN for audio.
- Return generated samples to the caller.

Applications own I/O. For example, `llama-tts` and `llama-cli --omtd` write WAV
files, while `llama-server` returns `/v1/audio/speech` responses. OMTD owns the
model-runtime dispatch and generated media pipeline.

## Public API

The public C API is declared in `omtd.h`.

Detection:

- `omtd_is_output_companion_gguf(path)`
- `omtd_get_model_type(path)`
- `omtd_get_model_modality(path)`

Generation:

- `omtd_audio_generate_file(params, error, error_size)`
- `omtd_higgs_tts_main(argc, argv)`

`omtd_audio_generate_file()` is the structured API used by `llama-server`.
`omtd_higgs_tts_main()` is a compatibility CLI entry point used by `llama-tts`,
`llama-higgs-tts`, `llama-higgs-probe`, and `llama-cli --omtd`.

## Supported Model Detection

In this implementation, OMTD recognizes Higgs Audio v3 companion GGUF files by
checking:

```text
higgs_audio.format == "higgs-audio-v3-tts"
```

Unknown files return:

```text
OMTD_MODEL_TYPE_UNKNOWN
OMTD_MODALITY_UNKNOWN
```

This lets frontends distinguish OMTD output companions from MTMD `mmproj`
projectors before trying to run them.

## Build Integration

`tools/omtd/CMakeLists.txt` builds `omtd` as a public library. It links only
against public llama.cpp/ggml boundaries:

```text
omtd -> llama, ggml
```

It intentionally must not link `llama-common`. This keeps OMTD usable as a
library boundary instead of only as an internal tool helper.

The current Higgs implementation is compiled into `omtd` from
`tools/tts/higgs_v3/higgs-probe.cpp` with `HIGGS_TTS_NO_MAIN` set. This avoids
duplicating the Higgs runtime while allowing multiple tools to share the same
OMTD entry point.

## Frontends

Current frontends are:

- `llama-tts --omtd FILE`
- `llama-cli --omtd FILE`
- `llama-server --omtd FILE` with `/v1/audio/speech`
- `llama-higgs-tts`
- `llama-higgs-probe`

For CLI/server usage, pass an output companion with `--omtd FILE`.
`--mmproj FILE` is reserved for MTMD input-media projectors.

Higgs voice cloning should use `--ref-voice reference.wav` or the structured API
field `ref_voice_path`. The implementation creates/reuses a same-stem
`reference.json` code sidecar beside the WAV and auto-loads `reference.txt` as
the transcript when it exists. Use `--ref-text reference.txt` or
`ref_text_path` to provide a different transcript file explicitly.

## OMTD vs MTMD

| Area | MTMD | OMTD |
| --- | --- | --- |
| Direction | Media input to text model | Text model to generated media output |
| Main flag | `--mmproj` | `--omtd` |
| File role | Input projector/encoder GGUF | Output companion/decoder GGUF |
| Current modalities | Image, audio, video input | Audio output |
| Current main API | `mtmd_tokenize`, `mtmd_encode`, helpers | `omtd_audio_generate_file`, detection helpers |
| Frontends | `llama-cli`, `llama-server`, `llama-mtmd-cli` | `llama-tts`, `llama-cli`, `llama-server` speech |
| Data ownership | Caller provides media and receives embeddings/chunks | Caller provides prompt/settings and receives generated media |
| Server endpoint | Chat/completions with media content | `/v1/audio/speech` |

MTMD preprocesses media into embeddings that are inserted into a normal language
model prompt. OMTD runs an output model pipeline after or around text-model
generation, then decodes generated media.

## Current Limitations

- Higgs Audio v3 is the only implemented OMTD model type.
- Image and video output enums are placeholders for future output generators.
- The structured API currently writes audio to a file path.
- `omtd_higgs_tts_main()` is still a CLI-compatibility bridge around the Higgs
  runtime.
- OMTD does not provide an MTMD-style helper layer for media serialization yet.

See `docs/omtd.md` for the fuller design and usage documentation.
