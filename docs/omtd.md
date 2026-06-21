# Output Multimodal Runtime

OMTD is the output-side multimodal runtime for llama.cpp. It is designed for
models that take text-model state, generated tokens, or hidden states and
produce non-text media such as audio, images, or video.

The current implementation supports Higgs Audio v3 text-to-speech as the first
OMTD model.

## Relationship to MTMD

MTMD and OMTD solve opposite sides of multimodal work.

MTMD is input-side multimodal:

```text
image/audio/video input -> preprocessor/projector -> embeddings -> llama model -> text output
```

OMTD is output-side multimodal:

```text
text prompt -> llama/output model pipeline -> generated media decoder -> audio/image/video output
```

For this reason the command-line flags are intentionally separate:

- `--mmproj FILE` loads an MTMD input projector.
- `--omtd FILE` loads an OMTD output companion.

Do not pass a Higgs Audio v3 OMTD companion to `--mmproj`. It is not an MTMD
projector and should be loaded through `--omtd`.

## Why OMTD Exists

MTMD already provides a clean way to turn media inputs into model embeddings,
but output-generation models have different needs:

- They may need model-specific generation loops.
- They may consume hidden states instead of only text tokens.
- They may use output codebooks, acoustic latents, vocoders, diffusion decoders,
  or other decoders that are not input projectors.
- Their output is binary media, not a token sequence.

OMTD keeps that output-side complexity outside `libllama` while giving tools a
single place to detect, load, and run output companions.

## Current Architecture

The public library lives in:

```text
tools/omtd/
```

Important files:

- `tools/omtd/omtd.h`: public C API
- `tools/omtd/omtd.cpp`: model detection and structured dispatch
- `tools/omtd/CMakeLists.txt`: public library build
- `tools/tts/higgs_v3/higgs-probe.cpp`: current Higgs Audio v3 runtime used by OMTD
- `tests/test-omtd.cpp`: OMTD companion detection test

The current `omtd` target links against:

```text
llama
ggml
Threads
OpenMP, when available
```

It intentionally does not link `llama-common`, matching the same public-library
boundary rule used by MTMD.

## Public API

The public API is C-compatible and declared in `tools/omtd/omtd.h`.

### Model and Modality Types

```c
typedef enum omtd_modality {
    OMTD_MODALITY_UNKNOWN = 0,
    OMTD_MODALITY_AUDIO   = 1,
    OMTD_MODALITY_IMAGE   = 2,
    OMTD_MODALITY_VIDEO   = 3,
} omtd_modality;

typedef enum omtd_model_type {
    OMTD_MODEL_TYPE_UNKNOWN        = 0,
    OMTD_MODEL_TYPE_HIGGS_AUDIO_V3 = 1,
} omtd_model_type;
```

Image and video are reserved API slots. They are not implemented yet.

### Status Codes

```c
typedef enum omtd_status {
    OMTD_STATUS_SUCCESS       = 0,
    OMTD_STATUS_INVALID_PARAM = 1,
    OMTD_STATUS_UNSUPPORTED   = 2,
    OMTD_STATUS_RUNTIME_ERROR = 3,
} omtd_status;
```

### Detection Functions

```c
bool omtd_is_output_companion_gguf(const char * path);
omtd_model_type omtd_get_model_type(const char * path);
omtd_modality omtd_get_model_modality(const char * path);
```

The current implementation detects Higgs Audio v3 companion GGUF files by
checking this metadata:

```text
higgs_audio.format == "higgs-audio-v3-tts"
```

Unknown or invalid files return `OMTD_MODEL_TYPE_UNKNOWN` and
`OMTD_MODALITY_UNKNOWN`.

### Audio Generation Parameters

```c
typedef struct omtd_audio_generation_params {
    const char * model_path;
    const char * companion_path;
    const char * prompt;
    const char * output_path;

    const char * device;
    const char * omtd_backend;
    const char * rvq_backend;
    const char * vocoder_backend;

    const char * ref_voice_path;
    const char * ref_text_path;

    int32_t n_gpu_layers;
    int32_t n_ctx;

    float duration_seconds;
    float max_duration_seconds;
    float temperature;
    int32_t top_k;
    int32_t seed;
    int32_t stream_stride;
    int32_t stream_holdback;

    bool seed_is_set;
    bool stream_wav;
    bool raw_prompt;
    bool verbose;
    bool flash_attn;
} omtd_audio_generation_params;
```

Important fields:

- `model_path`: backbone GGUF, currently the Qwen3 text backbone for Higgs.
- `companion_path`: OMTD companion GGUF, currently `higgs-audio-f16.gguf`.
- `prompt`: text to synthesize.
- `output_path`: WAV path to write.
- `device`: llama.cpp device placement for the backbone.
- `omtd_backend`: output codebook backend, for example `CUDA0` or `Vulkan1`.
- `rvq_backend`: RVQ decoder backend.
- `vocoder_backend`: DAC/BigVGAN backend.
- `ref_voice_path`: optional WAV reference clip for voice cloning. The Higgs
  implementation creates or reuses a same-stem JSON sidecar beside the WAV.
- `ref_text_path`: optional transcript file matching the reference voice clip.
- `seed_is_set`: when false, the Higgs sampler uses a fresh random seed.

### Audio Generation Function

```c
omtd_status omtd_audio_generate_file(
        const omtd_audio_generation_params * params,
        char * error,
        size_t error_size);
```

This validates parameters, verifies that the companion GGUF is supported, and
runs the current audio pipeline. On failure, `error` receives a short diagnostic
message when a buffer is provided.

The function currently writes a WAV file to `output_path`. Future API additions
can expose in-memory media buffers without changing the existing file API.

### CLI Bridge

```c
int omtd_higgs_tts_main(int argc, char ** argv);
```

This is a compatibility entry point for tools that already expose the Higgs TTS
command-line interface. It is used by:

- `llama-tts`
- `llama-cli --omtd`
- `llama-higgs-tts`
- `llama-higgs-probe`

## Higgs Audio v3 Pipeline

Higgs Audio v3 is represented by two GGUF files:

- Backbone GGUF: Qwen3 text model.
- OMTD companion GGUF: Higgs audio metadata and audio tensors.

The generation path is:

```text
text prompt
-> Higgs TTS prompt wrapper
-> Qwen3 backbone decode
-> hidden state for each generated step
-> Higgs codebook head
-> delayed codebook frames
-> reverse delay pattern
-> RVQ acoustic latents
-> DAC/BigVGAN vocoder
-> 24 kHz mono float WAV
```

The companion GGUF contains the output-side tensors needed for this path:

- fused codebook embedding
- fused codebook output head
- RVQ decoder weights
- DAC/BigVGAN vocoder weights
- HuBERT/semantic/acoustic/reference-encoder tensors used by native reference
  encoding

Backend placement is split because different stages have different performance
profiles:

- `--device`: backbone placement
- `--omtd-backend`: Higgs codebook projection backend
- `--omtd-rvq-backend`: RVQ decoder backend
- `--omtd-vocoder-backend`: DAC/BigVGAN decoder backend

## CLI Usage

Generate audio with `llama-cli`:

```bat
build-higgs-vulkan\bin\Release\llama-cli.exe ^
  --model models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan1 ^
  --omtd-backend Vulkan1 ^
  --omtd-rvq-backend Vulkan1 ^
  --omtd-vocoder-backend Vulkan1 ^
  --temp 0.8 ^
  --top-k 50 ^
  -p "If you actually care about yourself" ^
  -o outputs\speech.wav
```

CUDA full-backend example:

```bat
build-higgs-cuda-ninja\bin\llama-cli.exe ^
  --model models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device CUDA0 ^
  --omtd-backend CUDA0 ^
  --omtd-rvq-backend CUDA0 ^
  --omtd-vocoder-backend CUDA0 ^
  --temp 0.8 ^
  --top-k 50 ^
  -p "If you actually care about yourself" ^
  -o outputs\speech-cuda.wav
```

Voice cloning with a WAV reference:

```bat
build-higgs-vulkan\bin\Release\llama-cli.exe ^
  --model models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan1 ^
  --omtd-backend Vulkan1 ^
  --omtd-rvq-backend Vulkan1 ^
  --omtd-vocoder-backend Vulkan1 ^
  --ref-voice refs\reference.wav ^
  --ref-text refs\reference.txt ^
  --temp 0.8 ^
  --top-k 50 ^
  -p "Target text in the reference voice." ^
  -o outputs\speech-cloned.wav
```

When `refs\reference.json` already exists, it is reused. When it does not
exist, the native Higgs reference encoder reads `refs\reference.wav` and writes
that sidecar automatically. `--ref-text` points to a transcript text file. If
`--ref-text` is omitted and `refs\reference.txt` exists, the same-stem
transcript is loaded automatically.

## Server Usage

Start the server with the OMTD companion:

```bat
build-higgs-vulkan\bin\Release\llama-server.exe ^
  -m models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan1 ^
  -c 1024 ^
  -np 1 ^
  --host 127.0.0.1 ^
  --port 8096
```

Call the speech endpoint:

```http
POST http://127.0.0.1:8096/v1/audio/speech
Content-Type: application/json
```

```json
{
  "input": "Text to synthesize locally.",
  "response_format": "wav",
  "ref_voice": "refs\\reference.wav",
  "omtd_backend": "Vulkan1",
  "omtd_rvq_backend": "Vulkan1",
  "omtd_vocoder_backend": "Vulkan1",
  "temperature": 0.8,
  "top_k": 50
}
```

The request may also provide `omtd` to override the server-level companion path.
Legacy `higgs_audio`, `higgs_backend`, `rvq_backend`, and `dac_backend` request
fields are accepted for compatibility, but the preferred fields are the
`omtd*` names.

## Comparison With MTMD

| Topic | MTMD | OMTD |
| --- | --- | --- |
| Direction | Input media to LLM | LLM or output model to generated media |
| Main library | `tools/mtmd` | `tools/omtd` |
| Main flag | `--mmproj` | `--omtd` |
| Companion file | Input projector/encoder GGUF | Output companion/decoder GGUF |
| Current modalities | Image, audio, video input | Audio output |
| Current dedicated tool | `llama-mtmd-cli` | `llama-tts`, `llama-higgs-tts`, `llama-higgs-probe` |
| Shared frontends | `llama-cli`, `llama-server` | `llama-cli`, `llama-server`, `llama-tts` |
| Server API | Chat/completions with media content | `/v1/audio/speech` |
| API shape | Tokenize media/text into chunks, encode media chunks | Detect output companion, generate media |
| Model state | Adds embeddings into llama context | Runs output generation and decoders |
| File decoding | Helper layer handles image/audio/video input files | Frontends provide prompts/settings and receive output files/responses |

MTMD's core flow is:

```text
bitmap/file -> mtmd_tokenize -> mtmd_input_chunks -> mtmd_encode -> embeddings -> llama_decode
```

OMTD's current Higgs flow is:

```text
prompt -> Higgs/Qwen3 generation -> codebooks -> RVQ -> DAC/BigVGAN -> WAV
```

MTMD preprocesses input media before or during prompt evaluation. OMTD produces
output media after or during output generation.

## Design Boundaries

OMTD should remain output-focused:

- It should not take ownership of `--mmproj`.
- It should not become a general media-input preprocessor.
- It should not require `llama-common` in the library target.
- It should keep model-specific generation details behind explicit model types.

MTMD should remain input-focused:

- It should keep `--mmproj` semantics.
- It should keep media input tokenization, preprocessing, and embedding.
- It should not be used to route output vocoders or generated-media decoders.

This split keeps command-line behavior predictable:

```text
--mmproj = media input
--omtd   = media output
```

## Extending OMTD

To add another output model type:

1. Add a new `omtd_model_type`.
2. Add or reuse an `omtd_modality`.
3. Add GGUF metadata detection in `omtd_get_model_type()`.
4. Add a model-specific generation API or a modality-level structured API.
5. Wire frontends to pass that companion through `--omtd`.
6. Add tests for companion detection and one minimal generation path.

Future image or video output models should not reuse audio-specific structures.
They should get separate parameter structs, for example:

```c
omtd_image_generation_params
omtd_video_generation_params
```

## Current Limitations

- Higgs Audio v3 is the only implemented model.
- Audio generation currently writes to a file in the structured API.
- Image and video output are API placeholders only.
- `omtd_higgs_tts_main()` is a compatibility bridge around the current Higgs
  runtime, not a generic OMTD command parser.
- OMTD does not yet have an MTMD-style helper layer for in-memory output
  serialization.

For Higgs-specific conversion and usage details, see
[`higgs-audio-v3.md`](multimodal/higgs-audio-v3.md).
