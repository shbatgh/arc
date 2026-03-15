#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <omp.h>
#include <cmath>
#include <msgpack.hpp>

namespace fs = std::filesystem;

// Constants
static constexpr double Z_SPACING = 3.0 / 0.198;
static constexpr double Z_SPACING_HALF = Z_SPACING * 0.5;

// Objects
struct Vec2 {
    double x = 0, y = 0;
    bool operator==(const Vec2& o) const { return x == o.x && y == o.y; }
    bool operator!=(const Vec2& o) const { return !(*this == o); }
    bool operator<(const Vec2& o) const { return x < o.x || (x == o.x && y < o.y); }
    bool operator>(const Vec2& o) const { return !(*this < o); }
    MSGPACK_DEFINE(x, y);
};

struct Vec3 {
    double x = 0, y = 0, z = 0;
    bool operator==(const Vec3& o) const { return x == o.x && y == o.y && z == o.z; }
    bool operator!=(const Vec3& o) const { return !(*this == o); }
    bool operator<(const Vec3& o) const {
        if (x != o.x) return x < o.x;
        if (y != o.y) return y < o.y;
        return z < o.z;
    }
    bool operator>(const Vec3& o) const { return !(*this < o); }
    MSGPACK_DEFINE(x, y, z);
};

struct Color3 {
    int r = 0, g = 0, b = 0;
    bool operator==(const Color3& o) const { return r == o.r && g == o.g && b == o.b; }
    bool operator!=(const Color3& o) const { return !(*this == o); }
    bool operator<(const Color3& o) const {
        if (r != o.r) return r < o.r;
        if (g != o.g) return g < o.g;
        return b < o.b;
    }
    bool operator>(const Color3& o) const { return !(*this < o); }
    MSGPACK_DEFINE(r, g, b);
};

using Outline2D = std::vector<Vec2>;
using Outline3D = std::vector<Vec3>;
using SliceDict = std::map<Color3, std::vector<Outline2D>>;
using StackList = std::vector<SliceDict>;
using FrameDict = std::vector<StackList>;

struct Cell3D {
    int id;
    Color3 color;
    int starting_slice = 0, top_slice = 0;
    std::vector<Vec2> centers;
    std::vector<Outline2D> outlines;
};

struct Cell4D {
    int id;
    Color3 color;
    int starting_slice = 0, top_slice = 0;
    std::vector<Vec3> centers;
    std::vector<Outline3D> outlines;
};

// Math Utilities
static double dist2d(Vec2 a, Vec2 b) {
    double dx = a.x - b.x, dy = a.y - b.y;
    return std::sqrt(dx*dx + dy*dy);
}

static double dist3d(Vec3 a, Vec3 b) {
    double dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
    return std::sqrt(dx*dx + dy*dy + dz*dz);
}

static Vec2 find_center_2d(const Outline2D& pts) {
    if (pts.empty()) return {0, 0};
    double sumx = 0, sumy = 0;
    
    for (auto& p : pts) {
        sumx += p.x;
        sumy += p.y;
    }
    
   return {sumx / (double) pts.size(), sumy / (double) pts.size()}; 
}

static Vec3 find_center_3d(const Outline3D& pts) {
    if (pts.empty()) return {0, 0};
    double sumx = 0, sumy = 0, sumz = 0;
    
    for (auto& p : pts) {
        sumx += p.x;
        sumy += p.y;
        sumz += p.z;
    }
    
   return {sumx / (double) pts.size(), sumy / (double) pts.size(), sumz / (double) pts.size()}; 
}

// Serialization
void save_frame_dict(const FrameDict& frames, const std::string& path) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Failed to open output file");
    msgpack::pack(out, frames);
}

FrameDict load_frame_dict(const std::string& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) throw std::runtime_error("failed to open input file");

    const std::streamsize size = in.tellg();
    in.seekg(0, std::ios::beg);

    std::string buf(static_cast<size_t>(size), '\0');
    if (!in.read(buf.data(), size)) throw std::runtime_error("failed to read file");

    msgpack::object_handle oh = msgpack::unpack(buf.data(), buf.size());
    return oh.get().as<FrameDict>();
}

// Lexographic Renaming
static std::string trim_copy(const std::string& s) {
    size_t start = 0;
    while (start < s.size() && std::isspace(static_cast<unsigned char>(s[start]))) {
        ++start;
    }

    size_t end = s.size();
    while (end > start && std::isspace(static_cast<unsigned char>(s[end - 1]))) {
        --end;
    }
    return s.substr(start, end - start);
}

static bool has_suffix(const std::string& value, const std::string& suffix) {
    if (suffix.size() > value.size()) return false;
    return std::equal(suffix.rbegin(), suffix.rend(), value.rbegin());
}

static int parse_first_int_token(const std::string& text, int fallback) {
    for (size_t i = 0; i < text.size(); ++i) {
        if (!std::isdigit(static_cast<unsigned char>(text[i]))) continue;
        size_t j = i;
        while (j < text.size() && std::isdigit(static_cast<unsigned char>(text[j]))) {
            ++j;
        }
        try {
            return std::stoi(text.substr(i, j - i));
        } catch (...) {
            return fallback;
        }
    }
    return fallback;
}

static bool is_outline_txt_file(const fs::path& path) {
    if (!path.has_filename()) return false;
    const std::string name = path.filename().string();
    return has_suffix(name, "_cp_outlines.txt");
}

static bool is_mask_derived_outline(const fs::path& path) {
    if (!path.has_filename()) return false;
    const std::string name = path.filename().string();
    return has_suffix(name, "_cp_masks_cp_outlines.txt");
}

static Outline2D parse_outline_line(const std::string& line,
                                    const fs::path& source_path,
                                    int line_number,
                                    bool close_loop) {
    std::stringstream ss(line);
    std::string token;
    std::vector<double> vals;
    while (std::getline(ss, token, ',')) {
        token = trim_copy(token);
        if (token.empty()) continue;
        try {
            vals.push_back(std::stod(token));
        } catch (...) {
            throw std::runtime_error(
                "Invalid coordinate token in " + source_path.string() + ":" + std::to_string(line_number)
            );
        }
    }

    if (vals.empty()) return {};
    if ((vals.size() % 2) != 0) {
        throw std::runtime_error(
            "Odd number of coordinate values in " + source_path.string() + ":" + std::to_string(line_number)
        );
    }

    Outline2D outline;
    outline.reserve(vals.size() / 2 + (close_loop ? 3 : 0));
    for (size_t i = 0; i + 1 < vals.size(); i += 2) {
        outline.push_back({vals[i], vals[i + 1]});
    }

    if (close_loop && outline.size() >= 3) {
        outline.push_back(outline[0]);
        outline.push_back(outline[1]);
        outline.push_back(outline[2]);
    }
    return outline;
}

FrameDict read_outlines(const std::string& outlines_root,
                        Color3 color = {253, 0, 0},
                        bool close_loop = true) {
    const fs::path root(outlines_root);
    if (!fs::exists(root) || !fs::is_directory(root)) {
        throw std::runtime_error("Outlines root not found: " + outlines_root);
    }

    std::vector<std::pair<int, fs::path>> timepoint_dirs;
    for (const auto& entry : fs::directory_iterator(root)) {
        if (!entry.is_directory()) continue;
        const std::string name = entry.path().filename().string();
        const int tp_num = parse_first_int_token(name, std::numeric_limits<int>::max());
        timepoint_dirs.push_back({tp_num, entry.path()});
    }
    std::sort(timepoint_dirs.begin(), timepoint_dirs.end(),
              [](const auto& a, const auto& b) {
                  if (a.first != b.first) return a.first < b.first;
                  return a.second.filename().string() < b.second.filename().string();
              });

    FrameDict frame_dict;

    for (const auto& [tp_num, tp_dir] : timepoint_dirs) {
        (void)tp_num;
        std::vector<fs::path> all_txt_files;
        for (const auto& entry : fs::directory_iterator(tp_dir)) {
            if (!entry.is_regular_file()) continue;
            if (!is_outline_txt_file(entry.path())) continue;
            all_txt_files.push_back(entry.path());
        }

        struct SliceChoice {
            fs::path path;
            bool mask_derived = false;
        };

        std::map<int, SliceChoice> selected_by_slice;
        std::vector<fs::path> fallback_files;

        for (const auto& path : all_txt_files) {
            const std::string name = path.filename().string();
            const int slice_idx = parse_first_int_token(name, -1);
            const bool mask_derived = is_mask_derived_outline(path);

            if (slice_idx < 0) {
                fallback_files.push_back(path);
                continue;
            }

            auto it = selected_by_slice.find(slice_idx);
            if (it == selected_by_slice.end()) {
                selected_by_slice[slice_idx] = {path, mask_derived};
                continue;
            }

            const bool existing_is_mask = it->second.mask_derived;
            const bool should_replace = (existing_is_mask && !mask_derived) ||
                                        (existing_is_mask == mask_derived &&
                                         path.filename().string() < it->second.path.filename().string());
            if (should_replace) {
                it->second = {path, mask_derived};
            }
        }

        std::vector<fs::path> ordered_slice_files;
        for (const auto& [slice_idx, choice] : selected_by_slice) {
            (void)slice_idx;
            ordered_slice_files.push_back(choice.path);
        }
        std::sort(fallback_files.begin(), fallback_files.end());
        ordered_slice_files.insert(ordered_slice_files.end(), fallback_files.begin(), fallback_files.end());

        StackList stack;
        stack.reserve(ordered_slice_files.size());

        for (const auto& file_path : ordered_slice_files) {
            std::ifstream in(file_path);
            if (!in) {
                throw std::runtime_error("Failed to open outlines file: " + file_path.string());
            }

            std::vector<Outline2D> outlines;
            std::string line;
            int line_number = 0;
            while (std::getline(in, line)) {
                ++line_number;
                if (trim_copy(line).empty()) continue;
                auto outline = parse_outline_line(line, file_path, line_number, close_loop);
                if (!outline.empty()) {
                    outlines.push_back(std::move(outline));
                }
            }

            SliceDict slice_dict;
            if (!outlines.empty()) {
                slice_dict[color] = std::move(outlines);
            }
            stack.push_back(std::move(slice_dict));
        }

        frame_dict.push_back(std::move(stack));
    }

    return frame_dict;
}

int main() {
    FrameDict fd = read_outlines("output/segmentation/outlines");
    StackList t = [];
    SliceDict joe = [];
    
    std::vector<int> ids;
    std::map<int, Vec3> centers;
    #pragma omp parallel for
    for (size_t i = 0; i < fd.size(); ++i) {
        for (size_t j = 0; j < fd[i].size(); ++i) {
            for (auto& [color, all_outline2d] : fd[i][j]) {
                for (auto& outline2d : all_outline2d) {
                    Vec2 center = find_center_2d(outline2d);
                    
                }
            }
        }
    }

    return (fd.empty() || total_slices == 0) ? 1 : 0;
}
