#include "omtd.h"
#include "outetts/outetts.h"

#include <cstring>

static bool has_omtd_audio_arg(int argc, char ** argv) {
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--higgs-audio") == 0 || std::strcmp(argv[i], "--omtd") == 0) {
            return true;
        }
    }
    return false;
}

int main(int argc, char ** argv) {
    if (has_omtd_audio_arg(argc, argv)) {
        return omtd_higgs_tts_main(argc, argv);
    }

    return outetts_main(argc, argv);
}
