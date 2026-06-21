#include "omtd.h"

#include <cstdio>

static int check(bool cond, const char * msg) {
    if (!cond) {
        std::fprintf(stderr, "OMTD test failed: %s\n", msg);
        return 1;
    }
    return 0;
}

int main(int argc, char ** argv) {
    if (check(!omtd_is_output_companion_gguf(nullptr), "nullptr is not a companion")) return 1;
    if (check(!omtd_is_output_companion_gguf(""), "empty path is not a companion")) return 1;
    if (check(omtd_get_model_type("") == OMTD_MODEL_TYPE_UNKNOWN, "empty path has unknown model type")) return 1;
    if (check(omtd_get_model_modality("") == OMTD_MODALITY_UNKNOWN, "empty path has unknown modality")) return 1;

    if (argc > 1) {
        const char * path = argv[1];
        if (check(omtd_is_output_companion_gguf(path), "Higgs companion should be detected")) return 1;
        if (check(omtd_get_model_type(path) == OMTD_MODEL_TYPE_HIGGS_AUDIO_V3, "Higgs companion model type")) return 1;
        if (check(omtd_get_model_modality(path) == OMTD_MODALITY_AUDIO, "Higgs companion modality")) return 1;
    }

    return 0;
}
