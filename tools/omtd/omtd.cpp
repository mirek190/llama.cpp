#include "omtd.h"

#include "gguf.h"

#include <cstring>
#include <string>
#include <vector>

int higgs_tts_main(int argc, char ** argv);

static void omtd_set_error(char * error, const size_t error_size, const char * msg) {
    if (!error || error_size == 0) {
        return;
    }
    const char * text = msg ? msg : "";
    std::strncpy(error, text, error_size - 1);
    error[error_size - 1] = '\0';
}

static bool omtd_has_text(const char * value) {
    return value && value[0] != '\0';
}

extern "C" bool omtd_is_output_companion_gguf(const char * path) {
    return omtd_get_model_type(path) != OMTD_MODEL_TYPE_UNKNOWN;
}

extern "C" omtd_model_type omtd_get_model_type(const char * path) {
    if (!omtd_has_text(path)) {
        return OMTD_MODEL_TYPE_UNKNOWN;
    }

    gguf_init_params params {
        /*.no_alloc =*/ true,
        /*.ctx      =*/ nullptr,
    };

    gguf_context * ctx = gguf_init_from_file(path, params);
    if (!ctx) {
        return OMTD_MODEL_TYPE_UNKNOWN;
    }

    omtd_model_type type = OMTD_MODEL_TYPE_UNKNOWN;
    const int64_t key = gguf_find_key(ctx, "higgs_audio.format");
    if (key >= 0 &&
            gguf_get_kv_type(ctx, key) == GGUF_TYPE_STRING &&
            std::strcmp(gguf_get_val_str(ctx, key), "higgs-audio-v3-tts") == 0) {
        type = OMTD_MODEL_TYPE_HIGGS_AUDIO_V3;
    }

    gguf_free(ctx);
    return type;
}

extern "C" omtd_modality omtd_get_model_modality(const char * path) {
    switch (omtd_get_model_type(path)) {
        case OMTD_MODEL_TYPE_HIGGS_AUDIO_V3:
            return OMTD_MODALITY_AUDIO;
        case OMTD_MODEL_TYPE_UNKNOWN:
        default:
            return OMTD_MODALITY_UNKNOWN;
    }
}

extern "C" omtd_status omtd_audio_generate_file(
        const omtd_audio_generation_params * params,
        char * error,
        const size_t error_size) {
    if (!params) {
        omtd_set_error(error, error_size, "missing OMTD audio generation params");
        return OMTD_STATUS_INVALID_PARAM;
    }
    if (!omtd_has_text(params->model_path)) {
        omtd_set_error(error, error_size, "missing backbone model path");
        return OMTD_STATUS_INVALID_PARAM;
    }
    if (!omtd_has_text(params->companion_path)) {
        omtd_set_error(error, error_size, "missing OMTD companion path");
        return OMTD_STATUS_INVALID_PARAM;
    }
    if (!omtd_has_text(params->prompt)) {
        omtd_set_error(error, error_size, "missing audio generation prompt");
        return OMTD_STATUS_INVALID_PARAM;
    }
    if (!omtd_has_text(params->output_path)) {
        omtd_set_error(error, error_size, "missing output WAV path");
        return OMTD_STATUS_INVALID_PARAM;
    }
    if (omtd_get_model_type(params->companion_path) != OMTD_MODEL_TYPE_HIGGS_AUDIO_V3) {
        omtd_set_error(error, error_size, "unsupported OMTD audio companion model");
        return OMTD_STATUS_UNSUPPORTED;
    }

    std::vector<std::string> args;
    args.reserve(64);
    args.push_back("omtd-higgs-audio");
    args.push_back("-m");
    args.push_back(params->model_path);
    args.push_back("--higgs-audio");
    args.push_back(params->companion_path);
    args.push_back("-o");
    args.push_back(params->output_path);
    args.push_back("-p");
    args.push_back(params->prompt);

    auto add_pair = [&](const char * flag, const char * value) {
        if (omtd_has_text(value)) {
            args.push_back(flag);
            args.push_back(value);
        }
    };
    auto add_int_pair = [&](const char * flag, const int32_t value) {
        args.push_back(flag);
        args.push_back(std::to_string(value));
    };
    auto add_float_pair = [&](const char * flag, const float value) {
        args.push_back(flag);
        args.push_back(std::to_string(value));
    };

    add_pair("--device", params->device);
    add_pair("--higgs-backend", params->omtd_backend);
    add_pair("--rvq-backend", params->rvq_backend);
    add_pair("--dac-backend", params->vocoder_backend);
    add_pair("--ref-voice", params->ref_voice_path);
    add_pair("--ref-text", params->ref_text_path);

    if (params->n_gpu_layers >= 0) {
        add_int_pair("-ngl", params->n_gpu_layers);
    }
    if (params->n_ctx > 0) {
        add_int_pair("-c", params->n_ctx);
    }
    if (params->duration_seconds > 0.0f) {
        add_float_pair("--duration", params->duration_seconds);
    }
    if (params->max_duration_seconds > 0.0f) {
        add_float_pair("--max-duration", params->max_duration_seconds);
    }
    if (params->temperature >= 0.0f) {
        add_float_pair("--temp", params->temperature);
    }
    if (params->top_k > 0) {
        add_int_pair("--top-k", params->top_k);
    }
    if (params->seed_is_set) {
        add_int_pair("--seed", params->seed);
    }
    if (params->stream_wav) {
        args.push_back("--stream-wav");
        if (params->stream_stride > 0) {
            add_int_pair("--stream-stride", params->stream_stride);
        }
        if (params->stream_holdback >= 0) {
            add_int_pair("--stream-holdback", params->stream_holdback);
        }
    }
    if (params->raw_prompt) {
        args.push_back("--raw-prompt");
    }
    if (params->verbose) {
        args.push_back("--verbose");
    }
    args.push_back(params->flash_attn ? "--flash-attn" : "--no-flash-attn");

    std::vector<char *> argv;
    argv.reserve(args.size());
    for (std::string & arg : args) {
        argv.push_back(arg.data());
    }

    const int rc = higgs_tts_main((int) argv.size(), argv.data());
    if (rc != 0) {
        omtd_set_error(error, error_size, "OMTD Higgs audio generation failed");
        return OMTD_STATUS_RUNTIME_ERROR;
    }

    omtd_set_error(error, error_size, "");
    return OMTD_STATUS_SUCCESS;
}

extern "C" int omtd_higgs_tts_main(int argc, char ** argv) {
    return higgs_tts_main(argc, argv);
}
