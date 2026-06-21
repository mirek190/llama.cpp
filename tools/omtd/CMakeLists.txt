# omtd: output multimodal generation helpers

find_package(Threads REQUIRED)
find_package(OpenMP QUIET)

add_library(omtd
            omtd.cpp
            omtd.h
            ../tts/higgs_v3/higgs-probe.cpp
            )

target_compile_definitions(omtd PRIVATE HIGGS_TTS_NO_MAIN)
target_link_libraries     (omtd PUBLIC llama ggml)
target_link_libraries     (omtd PRIVATE Threads::Threads)
target_include_directories(omtd PUBLIC  .)
target_include_directories(omtd PRIVATE ../tts/higgs_v3 ../..)
target_compile_features   (omtd PRIVATE cxx_std_17)

if(OpenMP_CXX_FOUND)
    target_link_libraries(omtd PRIVATE OpenMP::OpenMP_CXX)
endif()

if (BUILD_SHARED_LIBS)
    set_target_properties     (omtd PROPERTIES POSITION_INDEPENDENT_CODE ON)
    target_compile_definitions(omtd PRIVATE LLAMA_BUILD)
    target_compile_definitions(omtd PUBLIC  LLAMA_SHARED)
endif()

set(OMTD_PUBLIC_HEADERS
    ${CMAKE_CURRENT_SOURCE_DIR}/omtd.h
    )

set_target_properties(omtd
    PROPERTIES
    VERSION ${LLAMA_INSTALL_VERSION}
    SOVERSION 0
    MACHO_CURRENT_VERSION 0
    PUBLIC_HEADER "${OMTD_PUBLIC_HEADERS}")

install(TARGETS omtd LIBRARY PUBLIC_HEADER)

# omtd must remain a public library boundary.
if (TARGET omtd)
    get_target_property(libs omtd LINK_LIBRARIES)
    if (libs AND "llama-common" IN_LIST libs)
        message(FATAL_ERROR "omtd is designed to be a public library.\n"
                            "It must not link against llama-common")
    endif()
endif()
