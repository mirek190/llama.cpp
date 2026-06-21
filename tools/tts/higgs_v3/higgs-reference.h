#pragma once

#include "higgs-codec.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace higgs_audio {

struct reference_wav_data {
    int sample_rate = 0;
    int channels = 0;
    std::vector<float> mono;
};

inline uint16_t ref_u16le(const unsigned char * p) {
    return (uint16_t) p[0] | ((uint16_t) p[1] << 8);
}

inline uint32_t ref_u32le(const unsigned char * p) {
    return (uint32_t) p[0] | ((uint32_t) p[1] << 8) | ((uint32_t) p[2] << 16) | ((uint32_t) p[3] << 24);
}

inline std::vector<unsigned char> reference_read_binary_file(const std::filesystem::path & path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        throw std::runtime_error("failed to open file: " + path.string());
    }
    return {
        std::istreambuf_iterator<char>(in),
        std::istreambuf_iterator<char>(),
    };
}

inline reference_wav_data reference_read_wav_mono(const std::filesystem::path & path) {
    const auto bytes = reference_read_binary_file(path);
    if (bytes.size() < 12 || std::memcmp(bytes.data(), "RIFF", 4) != 0 || std::memcmp(bytes.data() + 8, "WAVE", 4) != 0) {
        throw std::runtime_error("unsupported WAV: missing RIFF/WAVE header");
    }

    const unsigned char * fmt = nullptr;
    size_t fmt_size = 0;
    const unsigned char * data = nullptr;
    size_t data_size = 0;

    size_t off = 12;
    while (off + 8 <= bytes.size()) {
        const unsigned char * chunk = bytes.data() + off;
        const uint32_t size = ref_u32le(chunk + 4);
        const size_t start = off + 8;
        const size_t end = start + size;
        if (end > bytes.size()) {
            throw std::runtime_error("unsupported WAV: truncated chunk");
        }
        if (std::memcmp(chunk, "fmt ", 4) == 0) {
            fmt = bytes.data() + start;
            fmt_size = size;
        } else if (std::memcmp(chunk, "data", 4) == 0) {
            data = bytes.data() + start;
            data_size = size;
            break;
        }
        off = end + (size & 1u);
    }
    if (!fmt || fmt_size < 16 || !data) {
        throw std::runtime_error("unsupported WAV: missing fmt or data chunk");
    }

    const uint16_t audio_format = ref_u16le(fmt + 0);
    const uint16_t channels = ref_u16le(fmt + 2);
    const uint32_t sample_rate = ref_u32le(fmt + 4);
    const uint16_t block_align = ref_u16le(fmt + 12);
    const uint16_t bits = ref_u16le(fmt + 14);
    if (channels == 0 || sample_rate == 0 || block_align == 0) {
        throw std::runtime_error("unsupported WAV: invalid format values");
    }

    const size_t frames = data_size / block_align;
    reference_wav_data out;
    out.sample_rate = (int) sample_rate;
    out.channels = (int) channels;
    out.mono.resize(frames);

    for (size_t t = 0; t < frames; ++t) {
        const unsigned char * frame = data + t * block_align;
        double sum = 0.0;
        for (uint16_t ch = 0; ch < channels; ++ch) {
            if (audio_format == 1 && bits == 16) {
                int16_t v;
                std::memcpy(&v, frame + ch * 2, sizeof(v));
                sum += (double) v / 32768.0;
            } else if (audio_format == 3 && bits == 32) {
                float v;
                std::memcpy(&v, frame + ch * 4, sizeof(v));
                sum += v;
            } else {
                throw std::runtime_error("unsupported WAV: only PCM16 and float32 WAV are supported");
            }
        }
        out.mono[t] = (float) std::clamp(sum / (double) channels, -1.0, 1.0);
    }
    return out;
}

inline std::string reference_json_escape(const std::string & text) {
    std::string out;
    out.reserve(text.size());
    for (const char c : text) {
        if (c == '\\') out += "\\\\";
        else if (c == '"') out += "\\\"";
        else out += c;
    }
    return out;
}

inline void reference_write_codes_json(
        const std::filesystem::path & out_path,
        const std::filesystem::path & wav_path,
        int input_sample_rate,
        double trim_seconds,
        const std::vector<std::vector<int>> & frames) {
    const auto parent = out_path.parent_path();
    if (!parent.empty()) {
        std::filesystem::create_directories(parent);
    }

    std::ofstream out(out_path, std::ios::binary);
    if (!out) {
        throw std::runtime_error("failed to open output JSON: " + out_path.string());
    }

    out << "{\n";
    out << "  \"format\": \"higgs-audio-v3-codes\",\n";
    out << "  \"source\": \"tools/tts/higgs_v3/higgs-reference.h:native-hubert\",\n";
    out << "  \"sample_rate\": 24000,\n";
    out << "  \"frame_rate\": 25,\n";
    out << "  \"num_codebooks\": " << (frames.empty() ? 0 : frames[0].size()) << ",\n";
    out << "  \"codebook_size\": 1024,\n";
    out << "  \"reference_audio\": \"" << reference_json_escape(wav_path.string()) << "\",\n";
    out << "  \"reference_input_sample_rate\": " << input_sample_rate << ",\n";
    out << "  \"reference_trim_seconds\": " << trim_seconds << ",\n";
    out << "  \"codec_frames\": [\n";
    for (size_t t = 0; t < frames.size(); ++t) {
        out << "    [";
        for (size_t q = 0; q < frames[t].size(); ++q) {
            if (q) out << ", ";
            out << frames[t][q];
        }
        out << "]";
        if (t + 1 < frames.size()) out << ",";
        out << "\n";
    }
    out << "  ]\n";
    out << "}\n";
}

inline std::filesystem::path reference_codes_sidecar_path(const std::filesystem::path & wav_path) {
    std::filesystem::path out = wav_path;
    out.replace_extension(".json");
    return out;
}

inline std::filesystem::path reference_text_sidecar_path(const std::filesystem::path & wav_path) {
    std::filesystem::path out = wav_path;
    out.replace_extension(".txt");
    return out;
}

inline bool reference_read_text_if_exists(const std::filesystem::path & path, std::string & out) {
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }
    std::ostringstream ss;
    ss << in.rdbuf();
    out = ss.str();
    while (!out.empty() && (out.back() == '\n' || out.back() == '\r')) {
        out.pop_back();
    }
    return true;
}

inline std::filesystem::path reference_ensure_codes_sidecar(
        const companion_file & file,
        const std::filesystem::path & wav_path,
        double seconds,
        bool * created = nullptr) {
    const auto out_path = reference_codes_sidecar_path(wav_path);
    if (std::filesystem::exists(out_path)) {
        if (created) {
            *created = false;
        }
        return out_path;
    }

    const int dst_rate = file.metadata().sample_rate;
    reference_wav_data wav = reference_read_wav_mono(wav_path);
    std::vector<float> audio = resample_kaiser(wav.mono, (double) wav.sample_rate, (double) dst_rate);
    const size_t max_samples = std::max<size_t>((size_t) dst_rate, (size_t) std::llround(seconds * dst_rate));
    if (audio.size() > max_samples) {
        audio.resize(max_samples);
    }

    const auto codes = encode_reference_codes(file, audio);
    if (codes.empty()) {
        throw std::runtime_error("native Higgs reference encoder produced no codec frames");
    }

    reference_write_codes_json(out_path, wav_path, wav.sample_rate, seconds, codes);
    if (created) {
        *created = true;
    }
    return out_path;
}

} // namespace higgs_audio
