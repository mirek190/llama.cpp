# Higgs Audio v3 Local Port Status

This checkout has initial local support for the `bosonai/higgs-audio-v3-tts-4b`
checkpoint format.

## What Works

The Hugging Face checkpoint can be converted into a native llama.cpp GGUF for
the Qwen3 text backbone embedded in the Higgs TTS model:

```bat
python convert_hf_to_gguf.py higgs-audio-v3-tts-4b ^
  --outtype f16 ^
  --outfile higgs-qwen3-backbone-f16.gguf
```

The converter:

- detects `HiggsMultimodalQwen3ForConditionalGeneration`
- reads Qwen3 parameters from the nested `text_config`
- remaps Higgs text-backbone tensors from `body.*` and
  `tied.embedding.text_embedding.*` into normal Qwen3 GGUF tensor names
- skips Higgs-specific audio codec and multi-codebook tensors that the Qwen3
  runtime graph cannot execute

The Higgs audio/codebook tensors can also be exported into a companion GGUF:

```bat
python tools\tts\higgs_v3\convert_higgs_audio_to_gguf.py higgs-audio-v3-tts-4b ^
  --outtype f16 ^
  --outfile higgs-audio-f16.gguf
```

This companion file preserves the fused codebook embedding/head and the Higgs
audio v2 codec tensors under `higgs.*` names for native loader/runtime work.

The native Higgs delay-pattern sampler is available in
`tools/tts/higgs_v3/higgs-sampler.h`. It implements the 8-codebook startup delay,
end-of-code winddown, and delay-pattern encode/decode helpers used by Higgs
Audio v3 generation. The same helper also contains the CPU-side fused
codebook embedding and output-head projection routines needed to bridge Qwen3
hidden states with Higgs codebook frames, plus a direct greedy codebook step
from one hidden vector through the fused head and delay sampler.

The companion GGUF reader is available in `tools/tts/higgs_v3/higgs-gguf.h`. It opens
the audio GGUF without allocating tensor payloads, validates the Higgs metadata,
and locates the fused codebook embedding/head tensors for the next native TTS
runtime step. Codec tensors are stored with short `higgs.codec.0000` style names
because native GGUF tensor names must fit in `GGML_MAX_NAME`; the original
checkpoint names are preserved in GGUF metadata arrays.

The native codec path is available in `tools/tts/higgs_v3/higgs-codec.h`. It loads the
Higgs audio v2 residual vector quantizer tensors (`codebook.embed`,
`project_out.*`) plus `fc2.*` from the companion GGUF, decodes reverse-delay
codec frames into the 256-channel acoustic latent sequence, and runs a native
DAC decoder to produce PCM samples. The RVQ and DAC decoders have CPU reference
paths plus optional ggml backend graph paths for CUDA/Vulkan.

`llama-tts` now has a native Higgs mode for this split GGUF format through the
OMTD output-modality runtime. When `--higgs-audio` or `--omtd` is present it
loads the converted Qwen3 backbone plus the Higgs
companion GGUF, formats text as the Higgs zero-shot TTS prompt
(`<|tts|><|text|>...<|audio|>`), and runs a local autoregressive Higgs codebook
loop. Each generated codebook frame is embedded with the fused Higgs audio
embedding table and fed back into llama.cpp through the native embedding-input
batch path. It can write generated code JSON, raw F32 acoustic latents, and a
float WAV file:

```bat
build-higgs\bin\Debug\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --omtd-backend auto ^
  --steps 128 ^
  --codes-out outputs\higgs-native-codes.json ^
  --latents-out outputs\higgs-native-latents.f32 ^
  -o outputs\higgs-native-output.wav ^
  -p "Hello from native Higgs."
```

`llama-cli` also supports the same OMTD audio path. When `--omtd` is present,
the CLI dispatches directly to the Higgs/OMTD audio generator instead of
starting the normal interactive text chat loop:

```bat
build-higgs\bin\Release\llama-cli.exe ^
  -m models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan1 ^
  --omtd-backend Vulkan1 ^
  --omtd-rvq-backend Vulkan1 ^
  --omtd-vocoder-backend Vulkan1 ^
  --duration 1.6 ^
  -o outputs\higgs-cli-output.wav ^
  -p "Hello from native Higgs through llama-cli."
```

`--omtd-backend auto` selects the first non-CPU ggml device registered by the
current build, so it works with Vulkan, CUDA, Metal, SYCL, RPC, or other
llama.cpp backends when those backends are built or dynamically loadable. Use
`--list-omtd-backends` to print the exact device names for the current build:

```bat
build-higgs\bin\Debug\llama-tts.exe --omtd dummy --list-omtd-backends
```

For Vulkan builds, llama.cpp's ggml Vulkan backend requires the Vulkan SDK
development files, including `glslc`, Vulkan headers/libraries, and
SPIRV-Headers. A typical configure command is:

```bat
cmake -S . -B build-higgs-vulkan -DGGML_VULKAN=ON
cmake --build build-higgs-vulkan --target llama-tts --config Release
```

Then force a device by name, for example:

```bat
build-higgs\bin\Debug\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan0 ^
  --omtd-backend Vulkan0 ^
  -ngl 99 ^
  --duration 1.6 ^
  -o outputs\higgs-vulkan-output.wav ^
  -p "Hello from native Higgs on Vulkan."
```

For CUDA builds on Windows, the working local build uses Ninja through the
Visual Studio developer environment and targets RTX 30xx architecture 86:

```bat
VsDevCmd.bat -arch=x64 -host_arch=x64
cmake -S . -B build-higgs-cuda-ninja -G Ninja ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DGGML_CUDA=ON ^
  -DCMAKE_CUDA_ARCHITECTURES=86 ^
  -DGGML_CUDA_FORCE_CUBLAS=ON
cmake --build build-higgs-cuda-ninja --target llama-tts llama-higgs-tts llama-higgs-probe
```

Use CUDA by selecting `CUDA0` for the backbone, Higgs codebook head, RVQ
decoder, and DAC decoder:

```bat
build-higgs-cuda-ninja\bin\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device CUDA0 ^
  --omtd-backend CUDA0 ^
  --omtd-rvq-backend CUDA0 ^
  --omtd-vocoder-backend CUDA0 ^
  -ngl 99 ^
  --duration 1.6 ^
  -o outputs\higgs-cuda-output.wav ^
  -p "Hello from native Higgs on CUDA."
```

`--omtd-backend cpu` keeps the Higgs codebook projection on the original CPU
path. The Qwen3 backbone still follows normal llama.cpp backend placement via
`-ngl`, `--device`, and the build's available backend support. `--device` accepts
a comma-separated ggml device list for the backbone; `--omtd-backend` selects
the single device used for the native Higgs codebook-head matmul.
`--omtd-rvq-backend cpu` keeps the RVQ code-to-acoustic-latents decoder on the CPU
reference path, while `--omtd-rvq-backend CUDA0`,
`--omtd-rvq-backend Vulkan0`, or `--omtd-rvq-backend auto` runs it through a
ggml backend graph. `--omtd-vocoder-backend cpu` keeps the DAC decoder on the
CPU reference path, while `--omtd-vocoder-backend CUDA0`,
`--omtd-vocoder-backend Vulkan0`, or `--omtd-vocoder-backend auto` runs the
DAC decoder through a ggml backend graph. Streaming WAV output also honors these
backend flags, but it rebuilds the RVQ/DAC decode graphs for each streamed flush.

When `-o`, `--out`, or `--wav-out` is used and neither `--steps` nor
`--duration` is set, the tool estimates an automatic duration from text length
and punctuation. This is a safety cap for the current greedy native sampler; if
the model emits Higgs EOC earlier, generation still stops earlier. `--raw-prompt`
disables the default Higgs TTS prompt wrapper and is intended only for
diagnostics. Runtime model logs are quiet by default; use `--verbose` to restore
them. `--print-codes` prints each delayed Higgs codebook frame.
`llama-higgs-tts` and `llama-higgs-probe` build the same native path as
standalone entry points; the probe name prints codebook frames by default.

`llama-server` also exposes the native Higgs path as an OpenAI-style speech
endpoint. Pass the Higgs companion GGUF with `--omtd`. `--mmproj` is reserved
for MTMD input-media projectors and should not be used for Higgs output
companions.
For example:

```bat
build-higgs-vulkan\bin\Release\llama-server.exe ^
  -m models\higgs-qwen3-backbone-q8_0.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan1 ^
  -ngl 99 ^
  -c 1024 ^
  -np 1 ^
  --host 127.0.0.1 ^
  --port 8096
```

The raw HTTP endpoint is:

```bat
POST http://127.0.0.1:8096/v1/audio/speech
Content-Type: application/json

{
  "input": "Text to synthesize locally.",
  "response_format": "wav",
  "device": "CUDA0",
  "higgs_backend": "CUDA0",
  "rvq_backend": "CUDA0",
  "dac_backend": "CUDA0",
  "temperature": 0.8,
  "top_k": 50,
  "seed": 1234
}
```

Set the Higgs companion GGUF with the `--omtd` server argument, or the request
JSON `omtd` / `higgs_audio` field. `LLAMA_OMTD` and `LLAMA_HIGGS_AUDIO` are
accepted as local overrides. Set `LLAMA_HIGGS_CACHE_MODEL=1` and
`LLAMA_HIGGS_CACHE_CONTEXT=1`
before launching the server to keep the Higgs generation model/context resident
after the first speech request. This intentionally keeps VRAM near the higher
speech generation watermark instead of dropping back to the base server
footprint after every prompt.

If no duration is provided, the server estimates duration from text length.
Longer text creates more Higgs autoregressive steps; for example, an automatic
12.19 second estimate becomes 312 delayed codebook steps.

The native codebook sampler is greedy by default. Use `--temp` greater than
zero to sample each Higgs codebook row, `--top-k` to restrict sampling to the
largest K logits per codebook, and `--seed` for reproducible local sampling:

```bat
build-higgs-vulkan\bin\Release\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan0 ^
  --omtd-backend Vulkan0 ^
  --omtd-rvq-backend Vulkan0 ^
  --omtd-vocoder-backend Vulkan0 ^
  -ngl 99 ^
  --duration 2.0 ^
  --temp 0.8 ^
  --top-k 50 ^
  --seed 1234 ^
  -o outputs\higgs-sampled-output.wav ^
  -p "Sampled native Higgs output."
```

`--steps` counts delayed Higgs codebook steps, not final audio frames. With the
default 8 codebooks, usable codec frames are approximately `steps - 7`. The DAC
outputs 960 samples per codec frame at 24 kHz, and the default WAV writer stores
32-bit float samples. For example, `--steps 10` is only 3 codec frames, about
0.12 seconds and roughly 12 KB. Use `--duration 1.6` or `--steps 47` to force
roughly 1.6 seconds, about 150 KB.

The optional `--codes-out` file contains both `delayed_frames` and
reverse-delay `codec_frames`. The latter is the code layout expected by the
Higgs audio v2 decoder. The optional `--latents-out` file is raw little-endian
F32 with shape `[codec_frame_count, 256]`. The optional `--wav-out` file is a
mono 24 kHz IEEE-float WAV produced by the native DAC decoder.

Voice cloning is supported through `--ref-voice` in `llama-tts`,
`llama-cli --omtd`, and `llama-server` speech requests. Pass a WAV reference
clip. The runner creates or reuses a same-stem JSON sidecar beside the WAV,
reads its `codec_frames`, applies the Higgs delay pattern, feeds those frames as
native audio-codebook embeddings after `<|ref_audio|>`, then generates the
target text. `--ref-text` is optional and adds the matching reference
transcript from a text file. If `--ref-text` is omitted and a same-stem `.txt`
file exists next to the WAV, it is loaded automatically:

```bat
build-higgs-vulkan\bin\Release\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan0 ^
  --omtd-backend Vulkan0 ^
  -ngl 99 ^
  --duration 1.0 ^
  --ref-voice refs\reference.wav ^
  --ref-text refs\reference.txt ^
  -o outputs\higgs-ref-output.wav ^
  -p "Target text to speak in the reference voice."
```

The same cloned-voice generation can be run through `llama-cli`:

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
  -o outputs\higgs-cli-ref-output.wav ^
  -p "Target text to speak in the reference voice."
```

The same-stem sidecar convention is:

```text
refs\reference.wav  -> reference voice clip
refs\reference.json -> generated/reused reference code cache
refs\reference.txt  -> optional transcript loaded when --ref-text is omitted
```

Raw WAV reference clips can also be converted manually with the native C++
helper. This is optional because `--ref-voice` automatically creates or reuses
the same-stem reference JSON sidecar. The helper reads the HuBERT, semantic,
acoustic, FC and RVQ encoder weights from `higgs-audio-f16.gguf` and writes the
`codec_frames` layout used internally by the native runner:

```bat
build-higgs-vulkan\bin\Release\llama-higgs-reference-encode.exe ^
  --omtd models\higgs-audio-f16.gguf ^
  --wav refs\reference.wav ^
  --outfile refs\reference-codes.json ^
  --seconds 8.0
```

Normal cloning does not require this manual step because `--ref-voice` performs
it automatically. The generation runtime and the WAV-to-code preprocessing step
are both native/local.

`--stream-wav` writes the output WAV incrementally during generation. It decodes
stable accumulated frames every `--stream-stride` delayed rows and keeps
`--stream-holdback` delayed rows buffered before appending new PCM. The default
stride and holdback match the upstream streaming scheduler defaults closely
enough for local file streaming, while the final WAV header is fixed when
generation finishes:

```bat
build-higgs-vulkan\bin\Release\llama-tts.exe ^
  -m models\higgs-qwen3-backbone-f16.gguf ^
  --omtd models\higgs-audio-f16.gguf ^
  --device Vulkan0 ^
  --omtd-backend Vulkan0 ^
  -ngl 99 ^
  --duration 4.0 ^
  --stream-wav ^
  -o outputs\higgs-stream-output.wav ^
  -p "This WAV file grows while Higgs generation runs."
```

## Remaining Limitations

The current native path is intentionally focused on local execution. Remaining
work:

- richer sampling controls beyond temperature/top-k
- reusing the already-loaded primary server model instead of holding a second
  cached Higgs generation model/context for speech requests
- more backend graph coverage for the native HuBERT, semantic, acoustic, FC, and
  RVQ reference-encode path

The current native path is local and non-commercial-use oriented. It can produce
WAV output through `llama-tts --omtd`, `llama-cli --omtd`, and through
`llama-server /v1/audio/speech`; the Qwen3 backbone and Higgs codebook head can
use llama.cpp backends, and RVQ/DAC decoding can run through CUDA/Vulkan ggml
backend graphs for normal and streaming WAV output. This remains a focused
local runtime rather than a production-quality server integration.
