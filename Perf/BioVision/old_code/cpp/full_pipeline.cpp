/*
 * BioVision Full Pipeline - C++ Port
 *
 * Converts manually segmented 2D biological slice images into 3D meshes
 * with quantitative analysis of cell morphology and movement.
 * Ported from full_pipeline.py. Excludes segmentation (Python-only).
 *
 * Build (release):
 *   g++ -std=c++17 -O3 -march=native -DNDEBUG -o biovision_pipeline full_pipeline.cpp -lpthread
 *
 * Build with PNG support (requires stb_image.h in same directory):
 *   g++ -std=c++17 -O3 -march=native -DNDEBUG -DBIOVISION_HAS_STB_IMAGE -o biovision_pipeline full_pipeline.cpp -lpthread
 *
 * Build for profiling:
 *   g++ -std=c++17 -O2 -g -fno-omit-frame-pointer -o biovision_pipeline full_pipeline.cpp -lpthread
 */

#ifdef BIOVISION_HAS_STB_IMAGE
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#endif

#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

// ============================================================================
// Section 2: Constants
// ============================================================================

static constexpr double Z_SPACING_FULL    = 3.0 / 0.198;            // 15.1515...
static constexpr double DEFAULT_Z_SPACING = Z_SPACING_FULL * 0.5;   // 7.5757...
static constexpr double DIST_MULTIPLIER   = 0.7;
static constexpr int    DIST_TRAVEL_MULTIPLIER = 4;
static constexpr double TENSION       = -0.75;
static constexpr double CONTINUITY    = 0.0;
static constexpr double BIAS          = 0.0;
static constexpr int    POINTS_PER_SEGMENT = 8;
static constexpr int    MIN_LENGTH    = 14;
static constexpr int    NUM_CAP_LEVELS = 5;
static constexpr int    INTERP_PER_GAP = 7;
static constexpr int    MESH_NUM_POINTS = 96;
static constexpr int    MESH_SMOOTH_ITERS = 3;
static constexpr int    CONTOUR_NUM_POINTS = 64;
static constexpr int    CONTOUR_SMOOTH_ITERS = 5;
static constexpr int    ROUND_DECIMAL_PLACE = 1;

// ============================================================================
// Section 3: Core data structures
// ============================================================================

struct Vec2 {
    double x = 0, y = 0;
    bool operator==(const Vec2& o) const { return x == o.x && y == o.y; }
    bool operator!=(const Vec2& o) const { return !(*this == o); }
    bool operator<(const Vec2& o) const { return x < o.x || (x == o.x && y < o.y); }
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
};

static std::string color_str(Color3 c) {
    return "(" + std::to_string(c.r) + ", " + std::to_string(c.g) + ", " + std::to_string(c.b) + ")";
}

using Outline2D = std::vector<Vec2>;
using Outline3D = std::vector<Vec3>;
using SliceDict = std::map<Color3, std::vector<Outline2D>>;
using StackList = std::vector<SliceDict>;
using FrameDict = std::map<int, StackList>;

struct Cell {
    std::string id;
    Color3 color;
    int starting_slice = 0, top_slice = 0;
    std::vector<Vec2> centers;
    std::vector<Outline2D> outlines;
};

struct Cell3D {
    std::string id;
    Color3 color;
    int starting_tp = 0, final_tp = 0;
    std::vector<Vec3> centers3D;
    std::vector<Cell> cells_list;
};

struct TriMesh {
    std::vector<Vec3> vertices;
    std::vector<std::array<int,3>> faces;

    double volume() const {
        double vol = 0;
        for (auto& f : faces) {
            auto& v0 = vertices[f[0]];
            auto& v1 = vertices[f[1]];
            auto& v2 = vertices[f[2]];
            vol += v0.x * (v1.y * v2.z - v1.z * v2.y)
                 - v0.y * (v1.x * v2.z - v1.z * v2.x)
                 + v0.z * (v1.x * v2.y - v1.y * v2.x);
        }
        return std::abs(vol) / 6.0;
    }

    double surface_area() const {
        double area = 0;
        for (auto& f : faces) {
            auto& v0 = vertices[f[0]];
            auto& v1 = vertices[f[1]];
            auto& v2 = vertices[f[2]];
            double ex = (v1.x - v0.x), ey = (v1.y - v0.y), ez = (v1.z - v0.z);
            double fx = (v2.x - v0.x), fy = (v2.y - v0.y), fz = (v2.z - v0.z);
            double cx = ey*fz - ez*fy, cy = ez*fx - ex*fz, cz = ex*fy - ey*fx;
            area += std::sqrt(cx*cx + cy*cy + cz*cz);
        }
        return area * 0.5;
    }

    void fix_normals() {
        // Ensure consistent outward normals by checking signed volume
        double vol = 0;
        for (auto& f : faces) {
            auto& v0 = vertices[f[0]];
            auto& v1 = vertices[f[1]];
            auto& v2 = vertices[f[2]];
            vol += v0.x * (v1.y * v2.z - v1.z * v2.y)
                 - v0.y * (v1.x * v2.z - v1.z * v2.x)
                 + v0.z * (v1.x * v2.y - v1.y * v2.x);
        }
        if (vol < 0) {
            for (auto& f : faces) std::swap(f[1], f[2]);
        }
    }
};

// ============================================================================
// Section 4: Math utilities
// ============================================================================

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
    double sx = 0, sy = 0;
    for (auto& p : pts) { sx += p.x; sy += p.y; }
    return {sx / (double)pts.size(), sy / (double)pts.size()};
}

static double approx_width_2d(const Outline2D& pts, int comp) {
    if (pts.size() < 2) return 0;
    double mn = comp == 0 ? pts[0].x : pts[0].y;
    double mx = comp == 0 ? pts[1].x : pts[1].y;
    for (auto& p : pts) {
        double v = comp == 0 ? p.x : p.y;
        if (v < mn) mn = v;
        else if (v > mx) mx = v;
    }
    return mx - mn;
}

static double round_num(double v, int places) {
    double f = std::pow(10.0, places);
    return std::round(v * f) / f;
}

// ============================================================================
// Section 5: Pickle reader
// ============================================================================

struct PklValue {
    enum Type { NONE_T, INT_T, FLOAT_T, STRING_T, TUPLE_T, LIST_T, DICT_T, BOOL_T, BYTES_T, CALLABLE_T };
    Type type = NONE_T;
    int64_t ival = 0;
    double fval = 0.0;
    std::string sval;
    bool bval = false;
    std::vector<PklValue> items;                          // LIST_T / TUPLE_T
    std::vector<std::pair<PklValue, PklValue>> dict_items; // DICT_T

    double as_number() const { return type == INT_T ? (double)ival : fval; }

    bool operator==(const PklValue& o) const {
        if (type != o.type) return false;
        switch (type) {
            case NONE_T:   return true;
            case INT_T:    return ival == o.ival;
            case FLOAT_T:  return fval == o.fval;
            case STRING_T: case BYTES_T: case CALLABLE_T: return sval == o.sval;
            case BOOL_T:   return bval == o.bval;
            case TUPLE_T:
            case LIST_T:   return items == o.items;
            case DICT_T:   return dict_items == o.dict_items;
        }
        return false;
    }
    bool operator<(const PklValue& o) const {
        if (type != o.type) return type < o.type;
        switch (type) {
            case NONE_T:   return false;
            case INT_T:    return ival < o.ival;
            case FLOAT_T:  return fval < o.fval;
            case STRING_T: case BYTES_T: case CALLABLE_T: return sval < o.sval;
            case BOOL_T:   return bval < o.bval;
            case TUPLE_T:
            case LIST_T:   return items < o.items;
            case DICT_T:   return dict_items < o.dict_items;
        }
        return false;
    }

    static PklValue none()              { PklValue v; v.type = NONE_T; return v; }
    static PklValue integer(int64_t i)  { PklValue v; v.type = INT_T; v.ival = i; return v; }
    static PklValue floating(double d)  { PklValue v; v.type = FLOAT_T; v.fval = d; return v; }
    static PklValue string(std::string s) { PklValue v; v.type = STRING_T; v.sval = std::move(s); return v; }
    static PklValue boolean(bool b)     { PklValue v; v.type = BOOL_T; v.bval = b; return v; }
    static PklValue list()              { PklValue v; v.type = LIST_T; return v; }
    static PklValue tuple()             { PklValue v; v.type = TUPLE_T; return v; }
    static PklValue dict()              { PklValue v; v.type = DICT_T; return v; }
    static PklValue bytes(std::string s){ PklValue v; v.type = BYTES_T; v.sval = std::move(s); return v; }
    static PklValue callable(std::string name) { PklValue v; v.type = CALLABLE_T; v.sval = std::move(name); return v; }
};

static uint8_t read_u8(std::istream& in) {
    uint8_t b; in.read(reinterpret_cast<char*>(&b), 1); return b;
}
static uint16_t read_u16le(std::istream& in) {
    uint8_t buf[2]; in.read(reinterpret_cast<char*>(buf), 2);
    return (uint16_t)buf[0] | ((uint16_t)buf[1] << 8);
}
static int32_t read_i32le(std::istream& in) {
    uint8_t buf[4]; in.read(reinterpret_cast<char*>(buf), 4);
    return (int32_t)((uint32_t)buf[0] | ((uint32_t)buf[1]<<8) | ((uint32_t)buf[2]<<16) | ((uint32_t)buf[3]<<24));
}
static uint32_t read_u32le(std::istream& in) {
    uint8_t buf[4]; in.read(reinterpret_cast<char*>(buf), 4);
    return (uint32_t)buf[0] | ((uint32_t)buf[1]<<8) | ((uint32_t)buf[2]<<16) | ((uint32_t)buf[3]<<24);
}
static uint64_t read_u64le(std::istream& in) {
    uint8_t buf[8]; in.read(reinterpret_cast<char*>(buf), 8);
    uint64_t v = 0;
    for (int i = 7; i >= 0; i--) v = (v << 8) | buf[i];
    return v;
}
static double read_f64be(std::istream& in) {
    uint8_t buf[8]; in.read(reinterpret_cast<char*>(buf), 8);
    // Reverse to little-endian
    uint8_t le[8]; for (int i = 0; i < 8; i++) le[i] = buf[7 - i];
    double d; std::memcpy(&d, le, 8);
    return d;
}
static std::string read_bytes(std::istream& in, size_t n) {
    std::string s(n, '\0');
    in.read(s.data(), (std::streamsize)n);
    return s;
}

static PklValue pkl_read(std::istream& in) {
    constexpr int MARK_SENTINEL = -999;
    std::vector<PklValue> stack;
    std::vector<size_t> mark_positions;
    std::map<int, PklValue> memo;
    int next_memo_id = 0;

    auto push = [&](PklValue v) { stack.push_back(std::move(v)); };
    auto pop = [&]() -> PklValue {
        PklValue v = std::move(stack.back());
        stack.pop_back();
        return v;
    };
    for (;;) {
        uint8_t op = read_u8(in);
        if (!in.good()) throw std::runtime_error("Unexpected end of pickle stream");

        switch (op) {
        case 0x80: { // PROTO
            read_u8(in); // version, ignore
            break;
        }
        case 0x95: { // FRAME (protocol 4+, skip frame length)
            read_u64le(in);
            break;
        }
        case 0x7d: push(PklValue::dict()); break;   // EMPTY_DICT
        case 0x5d: push(PklValue::list()); break;   // EMPTY_LIST
        case 0x29: push(PklValue::tuple()); break;  // EMPTY_TUPLE
        case 0x4e: push(PklValue::none()); break;   // NONE
        case 0x88: push(PklValue::boolean(true)); break;  // NEWTRUE
        case 0x89: push(PklValue::boolean(false)); break; // NEWFALSE

        case 0x4b: push(PklValue::integer(read_u8(in))); break;   // BININT1
        case 0x4d: push(PklValue::integer(read_u16le(in))); break; // BININT2
        case 0x4a: push(PklValue::integer(read_i32le(in))); break; // BININT
        case 0x47: push(PklValue::floating(read_f64be(in))); break; // BINFLOAT

        case 0x8c: { // SHORT_BINUNICODE (1 byte len)
            int len = read_u8(in);
            push(PklValue::string(read_bytes(in, len)));
            break;
        }
        case 0x58: { // BINUNICODE (4 byte len)
            uint32_t len = read_u32le(in);
            push(PklValue::string(read_bytes(in, len)));
            break;
        }
        case 0x8d: { // BINUNICODE8 (8 byte len, protocol 4+)
            uint64_t len = read_u64le(in);
            push(PklValue::string(read_bytes(in, (size_t)len)));
            break;
        }
        case 0x28: { // MARK
            mark_positions.push_back(stack.size());
            break;
        }
        case 0x85: { // TUPLE1
            PklValue a = pop();
            PklValue t = PklValue::tuple();
            t.items.push_back(std::move(a));
            push(std::move(t));
            break;
        }
        case 0x86: { // TUPLE2
            PklValue b = pop(), a = pop();
            PklValue t = PklValue::tuple();
            t.items.push_back(std::move(a));
            t.items.push_back(std::move(b));
            push(std::move(t));
            break;
        }
        case 0x87: { // TUPLE3
            PklValue c = pop(), b = pop(), a = pop();
            PklValue t = PklValue::tuple();
            t.items.push_back(std::move(a));
            t.items.push_back(std::move(b));
            t.items.push_back(std::move(c));
            push(std::move(t));
            break;
        }
        case 0x74: { // TUPLE (from mark)
            size_t mark = mark_positions.back(); mark_positions.pop_back();
            PklValue t = PklValue::tuple();
            for (size_t i = mark; i < stack.size(); i++)
                t.items.push_back(std::move(stack[i]));
            stack.resize(mark);
            push(std::move(t));
            break;
        }
        case 0x61: { // APPEND
            PklValue item = pop();
            stack.back().items.push_back(std::move(item));
            break;
        }
        case 0x65: { // APPENDS (from mark)
            size_t mark = mark_positions.back(); mark_positions.pop_back();
            auto& target = stack[mark - 1];
            for (size_t i = mark; i < stack.size(); i++)
                target.items.push_back(std::move(stack[i]));
            stack.resize(mark);
            break;
        }
        case 0x73: { // SETITEM
            PklValue val = pop(), key = pop();
            stack.back().dict_items.emplace_back(std::move(key), std::move(val));
            break;
        }
        case 0x75: { // SETITEMS (from mark)
            size_t mark = mark_positions.back(); mark_positions.pop_back();
            auto& target = stack[mark - 1];
            for (size_t i = mark; i < stack.size(); i += 2)
                target.dict_items.emplace_back(std::move(stack[i]), std::move(stack[i+1]));
            stack.resize(mark);
            break;
        }
        case 0x71: { // BINPUT
            int idx = read_u8(in);
            memo[idx] = stack.back();
            break;
        }
        case 0x72: { // LONG_BINPUT
            int idx = (int)read_u32le(in);
            memo[idx] = stack.back();
            break;
        }
        case 0x68: { // BINGET
            int idx = read_u8(in);
            push(memo.at(idx));
            break;
        }
        case 0x6a: { // LONG_BINGET
            int idx = (int)read_u32le(in);
            push(memo.at(idx));
            break;
        }
        case 0x94: { // MEMOIZE (protocol 4+)
            memo[next_memo_id++] = stack.back();
            break;
        }
        case 0x43: { // SHORT_BINBYTES (protocol 3+)
            int len = read_u8(in);
            push(PklValue::bytes(read_bytes(in, len)));
            break;
        }
        case 0x93: { // STACK_GLOBAL: pop qualname + module, push callable marker
            PklValue qualname = pop();
            PklValue module = pop();
            push(PklValue::callable(module.sval + "." + qualname.sval));
            break;
        }
        case 0x52: { // REDUCE: pop args, pop callable, call
            PklValue args = pop();
            PklValue func = pop();
            // Handle numpy scalar: numpy._core.multiarray.scalar(dtype, bytes) -> float64
            if (func.type == PklValue::CALLABLE_T &&
                func.sval.find("scalar") != std::string::npos) {
                // args = (dtype, raw_bytes) — find the 8-byte item
                const PklValue* raw = nullptr;
                for (auto& item : args.items) {
                    if (item.type == PklValue::BYTES_T && item.sval.size() == 8) {
                        raw = &item; break;
                    }
                }
                if (raw) {
                    // Decode little-endian float64
                    uint64_t bits = 0;
                    for (int i = 7; i >= 0; i--)
                        bits = (bits << 8) | (uint8_t)raw->sval[i];
                    double d; std::memcpy(&d, &bits, 8);
                    push(PklValue::floating(d));
                    break;
                }
            }
            // Handle numpy dtype constructor: just push a placeholder callable
            if (func.type == PklValue::CALLABLE_T) {
                PklValue result = PklValue::callable(func.sval + "(...)");
                push(std::move(result));
                break;
            }
            // Generic fallback: push none
            push(PklValue::none());
            break;
        }
        case 0x62: { // BUILD: pop state, update top of stack (no-op for us)
            pop(); // discard state
            break;
        }
        case 0x2e: { // STOP
            return pop();
        }
        default:
            throw std::runtime_error("Unknown pickle opcode: 0x" +
                ([](uint8_t b) { char buf[8]; snprintf(buf, sizeof(buf), "%02x", b); return std::string(buf); })(op));
        }
    }
}

// ============================================================================
// Section 6: Pickle writer (protocol 2)
// ============================================================================

static void write_u8(std::ostream& out, uint8_t b) { out.put((char)b); }
static void write_u16le(std::ostream& out, uint16_t v) {
    uint8_t buf[2] = {(uint8_t)(v & 0xff), (uint8_t)(v >> 8)};
    out.write(reinterpret_cast<char*>(buf), 2);
}
static void write_i32le(std::ostream& out, int32_t v) {
    uint8_t buf[4];
    uint32_t u = (uint32_t)v;
    buf[0] = u & 0xff; buf[1] = (u>>8) & 0xff; buf[2] = (u>>16) & 0xff; buf[3] = (u>>24) & 0xff;
    out.write(reinterpret_cast<char*>(buf), 4);
}
static void write_u32le(std::ostream& out, uint32_t v) {
    uint8_t buf[4];
    buf[0] = v & 0xff; buf[1] = (v>>8) & 0xff; buf[2] = (v>>16) & 0xff; buf[3] = (v>>24) & 0xff;
    out.write(reinterpret_cast<char*>(buf), 4);
}
static void write_f64be(std::ostream& out, double d) {
    uint8_t buf[8]; std::memcpy(buf, &d, 8);
    uint8_t be[8]; for (int i = 0; i < 8; i++) be[i] = buf[7 - i];
    out.write(reinterpret_cast<char*>(be), 8);
}

static void pkl_write(std::ostream& out, const PklValue& val);

static void pkl_write_int(std::ostream& out, int64_t v) {
    if (v >= 0 && v <= 255) {
        write_u8(out, 0x4b); write_u8(out, (uint8_t)v);
    } else if (v >= 0 && v <= 65535) {
        write_u8(out, 0x4d); write_u16le(out, (uint16_t)v);
    } else {
        write_u8(out, 0x4a); write_i32le(out, (int32_t)v);
    }
}

static void pkl_write_string(std::ostream& out, const std::string& s) {
    // BINUNICODE (protocol 2)
    write_u8(out, 0x58);
    write_u32le(out, (uint32_t)s.size());
    out.write(s.data(), (std::streamsize)s.size());
}

static void pkl_write(std::ostream& out, const PklValue& val) {
    switch (val.type) {
    case PklValue::NONE_T:
        write_u8(out, 0x4e);
        break;
    case PklValue::BOOL_T:
        write_u8(out, val.bval ? 0x88 : 0x89);
        break;
    case PklValue::INT_T:
        pkl_write_int(out, val.ival);
        break;
    case PklValue::FLOAT_T:
        write_u8(out, 0x47);
        write_f64be(out, val.fval);
        break;
    case PklValue::STRING_T:
        pkl_write_string(out, val.sval);
        break;
    case PklValue::TUPLE_T: {
        if (val.items.empty()) {
            write_u8(out, 0x29); // EMPTY_TUPLE
        } else if (val.items.size() == 1) {
            pkl_write(out, val.items[0]);
            write_u8(out, 0x85); // TUPLE1
        } else if (val.items.size() == 2) {
            pkl_write(out, val.items[0]);
            pkl_write(out, val.items[1]);
            write_u8(out, 0x86); // TUPLE2
        } else if (val.items.size() == 3) {
            pkl_write(out, val.items[0]);
            pkl_write(out, val.items[1]);
            pkl_write(out, val.items[2]);
            write_u8(out, 0x87); // TUPLE3
        } else {
            write_u8(out, 0x28); // MARK
            for (auto& item : val.items) pkl_write(out, item);
            write_u8(out, 0x74); // TUPLE
        }
        break;
    }
    case PklValue::LIST_T: {
        write_u8(out, 0x5d); // EMPTY_LIST
        if (!val.items.empty()) {
            write_u8(out, 0x28); // MARK
            for (auto& item : val.items) pkl_write(out, item);
            write_u8(out, 0x65); // APPENDS
        }
        break;
    }
    case PklValue::DICT_T: {
        write_u8(out, 0x7d); // EMPTY_DICT
        if (!val.dict_items.empty()) {
            write_u8(out, 0x28); // MARK
            for (auto& [k, v] : val.dict_items) {
                pkl_write(out, k);
                pkl_write(out, v);
            }
            write_u8(out, 0x75); // SETITEMS
        }
        break;
    }
    }
}

static void pkl_write_file(std::ostream& out, const PklValue& val) {
    write_u8(out, 0x80); write_u8(out, 0x02); // PROTO 2
    pkl_write(out, val);
    write_u8(out, 0x2e); // STOP
}

// ============================================================================
// Pickle <-> typed data conversions
// ============================================================================

static Color3 pkl_to_color3(const PklValue& v) {
    return {(int)v.items[0].ival, (int)v.items[1].ival, (int)v.items[2].ival};
}

static PklValue color3_to_pkl(Color3 c) {
    PklValue t = PklValue::tuple();
    t.items.push_back(PklValue::integer(c.r));
    t.items.push_back(PklValue::integer(c.g));
    t.items.push_back(PklValue::integer(c.b));
    return t;
}

static FrameDict pkl_to_frame_dict(const PklValue& val) {
    FrameDict fd;
    for (auto& [kv, vv] : val.dict_items) {
        int tp = (int)kv.ival;
        StackList stack;
        for (auto& slice_val : vv.items) {
            SliceDict sd;
            for (auto& [ck, cv] : slice_val.dict_items) {
                Color3 color = pkl_to_color3(ck);
                std::vector<Outline2D> outlines;
                for (auto& outline_val : cv.items) {
                    Outline2D outline;
                    for (auto& pt_val : outline_val.items) {
                        outline.push_back({pt_val.items[0].as_number(), pt_val.items[1].as_number()});
                    }
                    outlines.push_back(std::move(outline));
                }
                sd[color] = std::move(outlines);
            }
            stack.push_back(std::move(sd));
        }
        fd[tp] = std::move(stack);
    }
    return fd;
}

static PklValue frame_dict_to_pkl(const FrameDict& fd) {
    PklValue d = PklValue::dict();
    for (auto& [tp, stack] : fd) {
        PklValue stack_list = PklValue::list();
        for (auto& sd : stack) {
            PklValue slice_dict = PklValue::dict();
            for (auto& [color, outlines] : sd) {
                PklValue key = color3_to_pkl(color);
                PklValue outline_list = PklValue::list();
                for (auto& outline : outlines) {
                    PklValue pts = PklValue::list();
                    for (auto& pt : outline) {
                        PklValue p = PklValue::list();
                        p.items.push_back(PklValue::floating(pt.x));
                        p.items.push_back(PklValue::floating(pt.y));
                        pts.items.push_back(std::move(p));
                    }
                    outline_list.items.push_back(std::move(pts));
                }
                slice_dict.dict_items.emplace_back(std::move(key), std::move(outline_list));
            }
            stack_list.items.push_back(std::move(slice_dict));
        }
        d.dict_items.emplace_back(PklValue::integer(tp), std::move(stack_list));
    }
    return d;
}

// Read header-prefixed pickle file
static std::pair<std::string, PklValue> read_header_pickle(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot open: " + path);
    std::string header;
    std::getline(in, header);
    PklValue val = pkl_read(in);
    return {header, std::move(val)};
}

// Write header-prefixed pickle file
static void write_header_pickle(const std::string& path, const std::string& header, const PklValue& val) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot write: " + path);
    out << header << "\n";
    pkl_write_file(out, val);
}

// ============================================================================
// Section 7: Image loader (conditional on stb_image)
// ============================================================================

struct RGBImage {
    int width = 0, height = 0;
    std::vector<uint8_t> data; // RGB, row-major, 3 bytes per pixel

    Color3 pixel(int x, int y) const {
        int idx = (y * width + x) * 3;
        return {data[idx], data[idx+1], data[idx+2]};
    }
};

static std::optional<RGBImage> load_image(const std::string& path) {
#ifdef BIOVISION_HAS_STB_IMAGE
    int w, h, channels;
    uint8_t* raw = stbi_load(path.c_str(), &w, &h, &channels, 3);
    if (!raw) return std::nullopt;
    RGBImage img;
    img.width = w; img.height = h;
    img.data.assign(raw, raw + w * h * 3);
    stbi_image_free(raw);
    return img;
#else
    (void)path;
    throw std::runtime_error("PNG loading requires BIOVISION_HAS_STB_IMAGE compile flag and stb_image.h");
#endif
}

// ============================================================================
// Section 8: Lexographic renaming
// ============================================================================

static void lex_rename(const std::string& path, bool is_file, int name_length) {
    std::vector<fs::path> items;
    for (auto& entry : fs::directory_iterator(path)) {
        if (is_file ? entry.is_regular_file() : entry.is_directory())
            items.push_back(entry.path());
    }
    if (items.empty()) return;

    if (name_length <= 0) {
        for (auto& p : items)
            name_length = std::max(name_length, (int)p.filename().string().size());
    }

    for (auto& cur : items) {
        std::string cur_name = cur.filename().string();
        if ((int)cur_name.size() >= name_length) continue;

        std::string new_name = cur_name;
        for (size_t i = 0; i < new_name.size(); i++) {
            if (std::isdigit((unsigned char)new_name[i])) {
                int pad = name_length - (int)new_name.size();
                new_name.insert(i, pad, '0');
                break;
            }
        }
        if (new_name != cur_name) {
            fs::rename(cur, cur.parent_path() / new_name);
        }
    }
}

static void run_lex_renaming(const fs::path& target_dir) {
    lex_rename(target_dir.string(), false, 0); // folders
    for (auto& entry : fs::directory_iterator(target_dir)) {
        if (entry.is_directory())
            lex_rename(entry.path().string(), true, 0); // files
    }
}

// ============================================================================
// Section 9: Reference point detection
// ============================================================================

static std::vector<int> find_image_dimensions(const fs::path& tp_root) {
    std::vector<fs::path> tp_dirs;
    for (auto& e : fs::directory_iterator(tp_root))
        if (e.is_directory()) tp_dirs.push_back(e.path());
    std::sort(tp_dirs.begin(), tp_dirs.end());

    std::vector<fs::path> files;
    for (auto& e : fs::directory_iterator(tp_dirs[0]))
        if (e.is_regular_file()) files.push_back(e.path());
    std::sort(files.begin(), files.end());

    auto img = load_image(files[0].string());
    if (!img) throw std::runtime_error("Cannot load image: " + files[0].string());
    std::cout << "Image dimensions: " << img->width << ", " << img->height << "\n";
    return {img->width, img->height};
}

static std::vector<std::vector<int>> find_ref_points(const fs::path& tp_root, Color3 ref_color,
                                                       int width, int height) {
    std::vector<fs::path> tp_dirs;
    for (auto& e : fs::directory_iterator(tp_root))
        if (e.is_directory()) tp_dirs.push_back(e.path());
    std::sort(tp_dirs.begin(), tp_dirs.end());

    std::vector<std::vector<int>> result;
    std::cout << "Finding reference points on timepoints: ";

    for (size_t tp = 0; tp < tp_dirs.size(); tp++) {
        std::cout << (tp + 1) << " " << std::flush;
        std::vector<fs::path> slices;
        for (auto& e : fs::directory_iterator(tp_dirs[tp]))
            if (e.is_regular_file()) slices.push_back(e.path());
        std::sort(slices.begin(), slices.end());

        std::vector<int> rx, ry;
        for (auto& sp : slices) {
            auto img = load_image(sp.string());
            if (!img) continue;
            for (int x = 0; x < std::min(width, img->width); x++) {
                for (int y = 0; y < std::min(height, img->height); y++) {
                    auto c = img->pixel(x, y);
                    if (c == ref_color) { rx.push_back(x); ry.push_back(y); }
                }
            }
        }

        if (!rx.empty()) {
            int ax = 0, ay = 0;
            for (auto v : rx) ax += v;
            for (auto v : ry) ay += v;
            result.push_back({ax / (int)rx.size(), ay / (int)ry.size()});
        } else {
            std::cout << "No ref point on t" << (tp + 1) << " ";
            result.push_back({0, 0});
        }
    }
    std::cout << "\n";
    return result;
}

// ============================================================================
// Section 10: Adjust algorithm
// ============================================================================

static Outline2D adjust_group(const Outline2D& group, Vec2 ref_pt, Vec2 rot_pt, bool should_rotate) {
    if (!should_rotate) {
        Outline2D result;
        for (auto& c : group)
            result.push_back({c.x - ref_pt.x, c.y - ref_pt.y});
        return result;
    }

    double angle = -std::atan((rot_pt.y - ref_pt.y) / (rot_pt.x - ref_pt.x));
    double cosA = std::cos(angle), sinA = std::sin(angle);
    bool flip = (ref_pt.x - rot_pt.x) < 0;

    Outline2D result;
    for (auto& c : group) {
        double ax = c.x - ref_pt.x, ay = c.y - ref_pt.y;
        double qx = cosA * ax - sinA * ay;
        double qy = sinA * ax + cosA * ay;
        if (flip) { qx = -qx; qy = -qy; }
        result.push_back({qx, qy});
    }
    result.push_back(result[0]);
    result.push_back(result[1]);
    return result;
}

// ============================================================================
// Section 11: Robust outline sorting
// ============================================================================

static double distance_sq(Vec2 a, Vec2 b) {
    return (a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y);
}

static bool ccw(Vec2 A, Vec2 B, Vec2 C) {
    return (C.y - A.y) * (B.x - A.x) > (B.y - A.y) * (C.x - A.x);
}

static bool segments_intersect(Vec2 A, Vec2 B, Vec2 C, Vec2 D) {
    return ccw(A, C, D) != ccw(B, C, D) && ccw(A, B, C) != ccw(A, B, D);
}

static std::vector<int> nearest_neighbor_order(const Outline2D& points) {
    int n = (int)points.size();
    std::vector<bool> visited(n, false);
    std::vector<int> order = {0};
    visited[0] = true;

    for (int step = 0; step < n - 1; step++) {
        int cur = order.back();
        double best_sq = std::numeric_limits<double>::infinity();
        int best = -1;
        for (int j = 0; j < n; j++) {
            if (!visited[j]) {
                double d = distance_sq(points[cur], points[j]);
                if (d < best_sq) { best_sq = d; best = j; }
            }
        }
        order.push_back(best);
        visited[best] = true;
    }
    return order;
}

static void two_opt(const Outline2D& points, std::vector<int>& order) {
    int n = (int)order.size();
    bool improved = true;
    while (improved) {
        improved = false;
        for (int i = 0; i < n - 1; i++) {
            for (int j = i + 2; j < n; j++) {
                if (i == 0 && j == n - 1) continue;
                Vec2 A = points[order[i]];
                Vec2 B = points[order[i + 1]];
                Vec2 C = points[order[j]];
                Vec2 D = points[order[(j + 1) % n]];
                if (segments_intersect(A, B, C, D)) {
                    std::reverse(order.begin() + i + 1, order.begin() + j + 1);
                    improved = true;
                }
            }
        }
    }
}

static Outline2D robust_sort_group(const Outline2D& group) {
    if (group.size() <= 3) return group;
    auto order = nearest_neighbor_order(group);
    two_opt(group, order);
    Outline2D result;
    for (int idx : order) result.push_back(group[idx]);
    return result;
}

// ============================================================================
// Section 12: Manual segmentation formatter
// ============================================================================

static Outline2D vf_get_surrounding(const RGBImage& img, Vec2 pt, Color3 color,
                                     bool loose, int width, int height) {
    int px = (int)pt.x, py = (int)pt.y;
    std::vector<std::pair<int,int>> coords = {
        {px-1,py-1},{px-1,py},{px-1,py+1},
        {px,py-1},{px,py+1},
        {px+1,py-1},{px+1,py},{px+1,py+1}
    };
    if (loose) {
        int ys[] = {-2,-1,0,1,2};
        for (int y : ys) { coords.push_back({px-2, py+y}); coords.push_back({px+2, py+y}); }
        int xs[] = {-1,0,1};
        for (int x : xs) { coords.push_back({px+x, py-2}); coords.push_back({px+x, py+2}); }
    }

    Outline2D result;
    for (auto [cx, cy] : coords) {
        if (cx >= 0 && cx < width && cy >= 0 && cy < height) {
            if (img.pixel(cx, cy) == color)
                result.push_back({(double)cx, (double)cy});
        }
    }
    return result;
}

static Outline2D vf_flood_fill(const RGBImage& img, Vec2 start, Color3 color,
                                int width, int height) {
    Outline2D final_pts = {start};
    auto queued = vf_get_surrounding(img, start, color, true, width, height);

    while (!queued.empty()) {
        Outline2D temp;
        for (auto& qp : queued) {
            for (auto& np : vf_get_surrounding(img, qp, color, true, width, height)) {
                bool in_temp = std::find(temp.begin(), temp.end(), np) != temp.end();
                bool in_final = std::find(final_pts.begin(), final_pts.end(), np) != final_pts.end();
                if (!in_temp && !in_final)
                    temp.push_back(np);
            }
        }
        for (auto& p : queued) final_pts.push_back(p);
        queued = std::move(temp);
    }
    return final_pts;
}

static Outline2D vf_sorted_group(const Outline2D& group, Vec2 ref_pt, Vec2 rot_pt,
                                  bool should_rotate, Color3 color) {
    auto sorted = robust_sort_group(group);
    auto adjusted = adjust_group(sorted, ref_pt, rot_pt, should_rotate);

    // Sparse step (always 1 in current code)
    Outline2D fin;
    for (size_t i = 0; i < adjusted.size(); i++)
        fin.push_back(adjusted[i]);
    fin.push_back(fin[0]);
    fin.push_back(fin[1]);
    fin.push_back(fin[2]);
    return fin;
}

static SliceDict vf_format_slice(const RGBImage& img, Vec2 ref_pt, Vec2 rot_pt,
                                  bool should_rotate, int width, int height) {
    SliceDict sd;
    std::vector<Vec2> checked;

    for (int x = 0; x < width; x++) {
        for (int y = 0; y < height; y++) {
            Color3 color = img.pixel(x, y);
            if (color == Color3{0,0,0} || color == Color3{255,255,255}) continue;

            Vec2 pt{(double)x, (double)y};
            if (std::find(checked.begin(), checked.end(), pt) != checked.end()) continue;

            auto group = vf_flood_fill(img, pt, color, width, height);
            for (auto& p : group) checked.push_back(p);

            auto sorted = vf_sorted_group(group, ref_pt, rot_pt, should_rotate, color);
            sd[color].push_back(std::move(sorted));
        }
    }
    return sd;
}

static StackList vf_format_stack(const fs::path& tp_path, Vec2 ref_pt, Vec2 rot_pt,
                                  bool should_rotate, int width, int height) {
    std::cout << "\nFormatting stack " << tp_path.filename().string() << std::flush;
    std::vector<fs::path> slices;
    for (auto& e : fs::directory_iterator(tp_path))
        if (e.is_regular_file()) slices.push_back(e.path());
    std::sort(slices.begin(), slices.end());

    StackList stack;
    for (auto& sp : slices) {
        auto img = load_image(sp.string());
        if (!img) { stack.push_back({}); continue; }
        stack.push_back(vf_format_slice(*img, ref_pt, rot_pt, should_rotate, width, height));
    }
    return stack;
}

static FrameDict prepare_manual_data(const fs::path& tp_root,
                                      const std::vector<std::vector<int>>& ref_list,
                                      const std::vector<std::vector<int>>& rot_list,
                                      int width, int height, bool rotate) {
    std::cout << "Preparing Manual Data\n";
    std::vector<fs::path> tp_dirs;
    for (auto& e : fs::directory_iterator(tp_root))
        if (e.is_directory()) tp_dirs.push_back(e.path());
    std::sort(tp_dirs.begin(), tp_dirs.end());

    FrameDict fd;
    for (size_t tp = 0; tp < tp_dirs.size(); tp++) {
        Vec2 ref{(double)ref_list[tp][0], (double)ref_list[tp][1]};
        Vec2 rot{(double)rot_list[tp][0], (double)rot_list[tp][1]};
        fd[(int)tp] = vf_format_stack(tp_dirs[tp], ref, rot, rotate, width, height);
    }
    return fd;
}

// ============================================================================
// Section 13: Color extractor
// ============================================================================

static std::vector<Color3> extract_colors(const FrameDict& data, int skip_slice = 0) {
    std::vector<Color3> result;
    for (auto& [tp, stack] : data) {
        size_t start = (size_t)skip_slice;
        size_t end = stack.size() > (size_t)skip_slice ? stack.size() - skip_slice : 0;
        for (size_t s = start; s < end; s++) {
            for (auto& [color, outlines] : stack[s]) {
                if (std::find(result.begin(), result.end(), color) != result.end()) continue;
                for (auto& outline : outlines) {
                    if ((int)outline.size() > MIN_LENGTH) {
                        result.push_back(color);
                        break;
                    }
                }
            }
        }
    }
    return result;
}

// ============================================================================
// Section 14: Single-stack cell matching
// ============================================================================

struct SSMatchEntry {
    Vec2 cur_center;
    Outline2D cur_outline;
    Vec2 prev_center;
    Outline2D prev_outline;
    double distance;
};

static std::vector<Outline2D> ss_find_segs(const SliceDict& sd, Color3 color) {
    auto it = sd.find(color);
    if (it == sd.end()) return {};
    return it->second;
}

static std::vector<SSMatchEntry> ss_match_cells(const std::vector<Outline2D>& cur,
                                                  const std::vector<Outline2D>& prev) {
    std::vector<SSMatchEntry> matched;
    for (auto& cc : cur) {
        Vec2 cc_center = find_center_2d(cc);
        for (auto& pc : prev) {
            Vec2 pc_center = find_center_2d(pc);
            matched.push_back({cc_center, cc, pc_center, pc, dist2d(cc_center, pc_center)});
        }
    }
    std::sort(matched.begin(), matched.end(), [](auto& a, auto& b) { return a.distance < b.distance; });
    return matched;
}

static void ss_remove_pairs(std::vector<SSMatchEntry>& matched, const Vec2& center) {
    matched.erase(std::remove_if(matched.begin(), matched.end(), [&](auto& e) {
        return e.cur_center == center || e.prev_center == center;
    }), matched.end());
}

static double ss_find_max_error(const Outline2D& p1, const Outline2D& p2) {
    double r1 = std::max(approx_width_2d(p1, 0), approx_width_2d(p1, 1));
    double r2 = std::max(approx_width_2d(p2, 0), approx_width_2d(p2, 1));
    return std::max(r1, r2) * DIST_MULTIPLIER;
}

static bool ss_appears_before(const std::vector<SSMatchEntry>& matched, const Vec2& center, int loc) {
    for (int i = 0; i < loc; i++)
        if (matched[i].cur_center == center || matched[i].prev_center == center) return true;
    return false;
}

static std::vector<Vec2> ss_tag_centers(const std::vector<SSMatchEntry>& matched,
                                         const Vec2& center, int start_idx) {
    std::vector<Vec2> tagged;
    for (int i = start_idx; i < (int)matched.size(); i++) {
        Vec2 other;
        if (matched[i].cur_center == center) other = matched[i].prev_center;
        else if (matched[i].prev_center == center) other = matched[i].cur_center;
        else continue;
        if (!ss_appears_before(matched, other, i))
            tagged.push_back(other);
    }
    return tagged;
}

static std::vector<SSMatchEntry> ss_filter_pairs(std::vector<SSMatchEntry> matched) {
    std::vector<SSMatchEntry> filtered;
    while (!matched.empty()) {
        filtered.push_back(matched[0]);
        Vec2 c0 = matched[0].cur_center, c1 = matched[0].prev_center;
        std::vector<Vec2> tagged = {c0, c1};
        auto t0 = ss_tag_centers(matched, c0, 1);
        auto t1 = ss_tag_centers(matched, c1, 1);
        tagged.insert(tagged.end(), t0.begin(), t0.end());
        tagged.insert(tagged.end(), t1.begin(), t1.end());
        for (auto& c : tagged) ss_remove_pairs(matched, c);
    }

    std::vector<SSMatchEntry> result;
    for (auto& pair : filtered) {
        if (pair.distance < ss_find_max_error(pair.cur_outline, pair.prev_outline))
            result.push_back(pair);
    }
    return result;
}

static Cell* ss_identify_cell(std::vector<Cell>& cells, const Vec2& center, Color3 color) {
    for (auto& c : cells) {
        if (c.color == color) {
            for (auto& ctr : c.centers)
                if (ctr == center) return &c;
        }
    }
    return nullptr;
}

static Cell make_cell(int& count, int slice, const Outline2D& outline, Color3 color) {
    Cell c;
    c.id = "Cell" + color_str(color) + " " + std::to_string(count++);
    c.color = color;
    c.starting_slice = slice;
    c.top_slice = slice;
    c.centers.push_back(find_center_2d(outline));
    c.outlines.push_back(outline);
    return c;
}

static std::vector<Cell> compute_stack(const StackList& stack, Color3 color) {
    std::vector<Cell> cells;
    int cell_count = 0;

    // First slice
    auto first_segs = ss_find_segs(stack[0], color);
    for (auto& seg : first_segs)
        cells.push_back(make_cell(cell_count, 0, seg, color));

    // Subsequent slices
    for (int s = 1; s < (int)stack.size(); s++) {
        auto cur_segs = ss_find_segs(stack[s], color);
        auto prev_segs = ss_find_segs(stack[s - 1], color);

        if (cur_segs.empty()) continue;
        if (prev_segs.empty()) {
            for (auto& seg : cur_segs)
                cells.push_back(make_cell(cell_count, s, seg, color));
            continue;
        }

        auto matched = ss_match_cells(cur_segs, prev_segs);
        auto filtered = ss_filter_pairs(std::move(matched));

        for (auto& entry : filtered) {
            Cell* cell = ss_identify_cell(cells, entry.prev_center, color);
            if (cell) {
                cell->top_slice++;
                cell->outlines.push_back(entry.cur_outline);
                cell->centers.push_back(find_center_2d(entry.cur_outline));
            }
            auto it = std::find(cur_segs.begin(), cur_segs.end(), entry.cur_outline);
            if (it != cur_segs.end()) cur_segs.erase(it);
        }

        for (auto& seg : cur_segs)
            cells.push_back(make_cell(cell_count, s, seg, color));
    }
    return cells;
}

// ============================================================================
// Section 15: Animation cell matching
// ============================================================================

struct PAMatchEntry {
    Vec3 cur_center;
    Cell cur_cell;
    Vec3 prev_center;
    Cell prev_cell;
    double distance;
};

static Vec3 find_3d_center(const Cell& cell) {
    double sx = 0, sy = 0;
    int length = 0;
    for (auto& outline : cell.outlines) {
        length += (int)outline.size();
        for (auto& p : outline) { sx += p.x; sy += p.y; }
    }
    double z = (cell.top_slice + cell.starting_slice) * 0.5 * Z_SPACING_FULL;
    return {sx / length, sy / length, z};
}

static double pa_approx_width(const Cell& cell, int axis) {
    // axis: 0=x, 1=y, 2=z
    if (axis == 2) return (double)cell.outlines.size() * Z_SPACING_FULL;

    if (cell.outlines.empty() || cell.outlines[0].size() < 2) return 0;
    double mn = axis == 0 ? cell.outlines[0][0].x : cell.outlines[0][0].y;
    double mx = axis == 0 ? cell.outlines[0][1].x : cell.outlines[0][1].y;

    // Note: matches Python bug - returns after first outline
    for (auto& outline : cell.outlines) {
        for (auto& p : outline) {
            double v = axis == 0 ? p.x : p.y;
            if (v < mn) mn = v;
            else if (v > mx) mx = v;
        }
        return mx - mn;
    }
    return mx - mn;
}

static std::vector<PAMatchEntry> pa_match_cells(const std::vector<Cell>& cur,
                                                  const std::vector<Cell>& prev) {
    std::vector<PAMatchEntry> matched;
    for (auto& cc : cur) {
        Vec3 cc_center = find_3d_center(cc);
        for (auto& pc : prev) {
            Vec3 pc_center = find_3d_center(pc);
            matched.push_back({cc_center, cc, pc_center, pc, dist3d(cc_center, pc_center)});
        }
    }
    std::sort(matched.begin(), matched.end(), [](auto& a, auto& b) { return a.distance < b.distance; });
    return matched;
}

static void pa_remove_pairs(std::vector<PAMatchEntry>& matched, const Vec3& center) {
    matched.erase(std::remove_if(matched.begin(), matched.end(), [&](auto& e) {
        return e.cur_center == center || e.prev_center == center;
    }), matched.end());
}

static double pa_find_max_error(const Cell& c1, const Cell& c2) {
    double r1 = (pa_approx_width(c1, 0) + pa_approx_width(c1, 1) + pa_approx_width(c1, 2)) / 3.0;
    double r2 = (pa_approx_width(c2, 0) + pa_approx_width(c2, 1) + pa_approx_width(c2, 2)) / 3.0;
    return (r1 + r2) * 0.5 * DIST_TRAVEL_MULTIPLIER;
}

static bool pa_appears_before(const std::vector<PAMatchEntry>& matched, const Vec3& center, int loc) {
    for (int i = 0; i < loc; i++)
        if (matched[i].cur_center == center || matched[i].prev_center == center) return true;
    return false;
}

static std::vector<Vec3> pa_tag_centers(const std::vector<PAMatchEntry>& matched,
                                         const Vec3& center, int start_idx) {
    std::vector<Vec3> tagged;
    for (int i = start_idx; i < (int)matched.size(); i++) {
        Vec3 other;
        if (matched[i].cur_center == center) other = matched[i].prev_center;
        else if (matched[i].prev_center == center) other = matched[i].cur_center;
        else continue;
        if (!pa_appears_before(matched, other, i))
            tagged.push_back(other);
    }
    return tagged;
}

static std::vector<PAMatchEntry> pa_filter_pairs(std::vector<PAMatchEntry> matched) {
    std::vector<PAMatchEntry> filtered;
    while (!matched.empty()) {
        filtered.push_back(matched[0]);
        Vec3 c0 = matched[0].cur_center, c1 = matched[0].prev_center;
        std::vector<Vec3> tagged = {c0, c1};
        auto t0 = pa_tag_centers(matched, c0, 1);
        auto t1 = pa_tag_centers(matched, c1, 1);
        tagged.insert(tagged.end(), t0.begin(), t0.end());
        tagged.insert(tagged.end(), t1.begin(), t1.end());
        for (auto& c : tagged) pa_remove_pairs(matched, c);
    }

    std::vector<PAMatchEntry> result;
    for (auto& pair : filtered) {
        if (pair.distance < pa_find_max_error(pair.cur_cell, pair.prev_cell))
            result.push_back(pair);
    }
    return result;
}

static Cell3D* pa_identify_cell(std::vector<Cell3D>& cells, const Vec3& center, Color3 color) {
    for (auto& c : cells) {
        if (c.color == color) {
            for (auto& ctr : c.centers3D)
                if (ctr == center) return &c;
        }
    }
    return nullptr;
}

static Cell3D make_cell3d(int& count, int tp, const Cell& cell, Color3 color) {
    Cell3D c;
    c.id = std::to_string(count++) + "_" + color_str(color) + "_Cell3D";
    c.color = color;
    c.starting_tp = tp;
    c.final_tp = tp;
    c.centers3D.push_back(find_3d_center(cell));
    c.cells_list.push_back(cell);
    return c;
}

static std::vector<Cell3D> compute_animation(const std::vector<std::vector<Cell>>& all_raw, Color3 color) {
    std::vector<Cell3D> cells3d;
    int count = 0;

    // First timepoint
    for (auto& cell : all_raw[0])
        if (cell.color == color)
            cells3d.push_back(make_cell3d(count, 0, cell, color));

    // Subsequent timepoints
    for (int tp = 1; tp < (int)all_raw.size(); tp++) {
        std::vector<Cell> cur_cells, prev_cells;
        for (auto& c : all_raw[tp]) if (c.color == color) cur_cells.push_back(c);
        for (auto& c : all_raw[tp - 1]) if (c.color == color) prev_cells.push_back(c);

        if (cur_cells.empty()) continue;
        if (prev_cells.empty()) {
            for (auto& c : cur_cells)
                cells3d.push_back(make_cell3d(count, tp, c, color));
            continue;
        }

        auto matched = pa_match_cells(cur_cells, prev_cells);
        auto filtered = pa_filter_pairs(std::move(matched));

        for (auto& entry : filtered) {
            Cell3D* cell = pa_identify_cell(cells3d, entry.prev_center, color);
            if (cell) {
                cell->final_tp++;
                cell->cells_list.push_back(entry.cur_cell);
                cell->centers3D.push_back(find_3d_center(entry.cur_cell));
            }
            auto it = std::find_if(cur_cells.begin(), cur_cells.end(),
                [&](const Cell& c) { return c.id == entry.cur_cell.id; });
            if (it != cur_cells.end()) cur_cells.erase(it);
        }

        for (auto& c : cur_cells) {
            std::cout << "Cell divided/new, tp: " << tp << " ";
            cells3d.push_back(make_cell3d(count, tp, c, color));
        }
    }
    return cells3d;
}

// ============================================================================
// Section 16: Matched cell orchestrator
// ============================================================================

static bool matched_cell_filter(const Cell3D& cell) {
    int max_outline_len = 0;
    for (auto& c : cell.cells_list)
        for (auto& o : c.outlines)
            max_outline_len = std::max(max_outline_len, (int)o.size());
    return max_outline_len > 10;
}

static std::vector<Cell3D> get_cells3D(const FrameDict& data, const std::vector<Color3>& colors) {
    std::cout << "Matching stacks\n";
    std::vector<std::vector<Cell>> all_raw;

    for (auto& col : colors) {
        std::cout << color_str(col) << " " << std::flush;
        std::vector<std::vector<Cell>> cur_raw;
        for (auto& [tp, stack] : data)
            cur_raw.push_back(compute_stack(stack, col));

        if (all_raw.empty()) {
            all_raw = std::move(cur_raw);
        } else {
            for (size_t i = 0; i < all_raw.size(); i++)
                all_raw[i].insert(all_raw[i].end(), cur_raw[i].begin(), cur_raw[i].end());
        }
    }

    int num_tps = (int)all_raw.size();
    std::cout << "\nNumber of Timepoints: " << num_tps << "\n";

    std::cout << "Matching animation\n";
    std::vector<Cell3D> cells3d;
    for (auto& col : colors) {
        std::cout << color_str(col) << " " << std::flush;
        auto result = compute_animation(all_raw, col);
        cells3d.insert(cells3d.end(), result.begin(), result.end());
    }

    std::cout << "\nCells before filter: " << cells3d.size();
    cells3d.erase(std::remove_if(cells3d.begin(), cells3d.end(),
        [](const Cell3D& c) { return !matched_cell_filter(c); }), cells3d.end());
    std::cout << ", after: " << cells3d.size() << "\n";

    return cells3d;
}

// ============================================================================
// Section 17: Triple wireframe creation
// ============================================================================

static int ntw_comp_g; // 0=x, 1=y (set before use)

static std::pair<double,double> ntw_find_min_and_width(const std::vector<Outline2D>& outlines) {
    double mn = ntw_comp_g == 0 ? outlines[0][0].x : outlines[0][0].y;
    double mx = mn;
    for (auto& outline : outlines) {
        for (auto& c : outline) {
            double v = ntw_comp_g == 0 ? c.x : c.y;
            if (v < mn) mn = v;
            else if (v > mx) mx = v;
        }
    }
    return {mn, mx - mn};
}

static std::vector<double> ntw_find_planes(double mn, double width, int num_wfs, double wf_dist) {
    std::vector<double> planes;
    double start = (width / 2.0) - (((num_wfs - 1) / 2.0) * wf_dist) + mn;
    for (int i = 0; i < num_wfs; i++)
        planes.push_back(start + i * wf_dist);
    return planes;
}

static std::vector<Outline2D> ntw_new_sorted_outlines(const std::vector<Outline2D>& outlines) {
    auto sorted = outlines;
    for (int i = (int)sorted.size() - 1; i >= 0; i--)
        sorted.push_back(sorted[i]);
    return sorted;
}

static Vec2 ntw_find_point(const Outline2D& pts, double plane_val, bool find_max, double wf_offset) {
    int sc = (ntw_comp_g + 1) % 2;
    std::vector<Vec2> valids;
    for (auto& p : pts) {
        double v = ntw_comp_g == 0 ? p.x : p.y;
        if (std::abs(plane_val - v) < wf_offset)
            valids.push_back(p);
    }
    if (valids.empty()) return {-1e18, -1e18}; // sentinel

    Vec2 result = valids[0];
    double extreme = sc == 0 ? result.x : result.y;
    for (auto& p : valids) {
        double v = sc == 0 ? p.x : p.y;
        if (find_max ? (v > extreme) : (v < extreme)) {
            extreme = v;
            result = p;
        }
    }
    return result;
}

static Outline3D ntw_create_wf_list(const std::vector<Outline2D>& sorted_outlines,
                                     double plane_val, double z_start, double wf_offset) {
    int num_slices = (int)sorted_outlines.size() / 2;
    double wf_h = Z_SPACING_FULL;

    std::map<int, Vec3> up_dict, down_dict;
    for (int i = 0; i < num_slices; i++) {
        double z = z_start + i * wf_h;
        Vec2 pt = ntw_find_point(sorted_outlines[i], plane_val, false, wf_offset);
        if (pt.x < -1e17) continue;
        up_dict[i] = {pt.x, pt.y, z};
    }
    for (int i = num_slices; i < 2 * num_slices; i++) {
        int mirror = 2 * num_slices - i - 1;
        double z = z_start + mirror * wf_h;
        Vec2 pt = ntw_find_point(sorted_outlines[i], plane_val, true, wf_offset);
        if (pt.x < -1e17) continue;
        down_dict[mirror] = {pt.x, pt.y, z};
    }

    Outline3D up_list, down_list;
    for (auto& [idx, pt] : up_dict) {
        if (down_dict.count(idx)) {
            up_list.push_back(pt);
            down_list.push_back(down_dict[idx]);
        }
    }

    Outline3D wf = up_list;
    for (int i = (int)down_list.size() - 1; i >= 0; i--)
        wf.push_back(down_list[i]);
    return wf;
}

static std::vector<Outline3D> ntw_triple_wireframe_creation(
    std::vector<Outline2D> outlines, int x_or_y, int starting_slice,
    double wf_dist, double wf_offset)
{
    ntw_comp_g = x_or_y; // 0=x, 1=y
    auto [mn, width] = ntw_find_min_and_width(outlines);
    int num_wfs = std::max(0, (int)std::round(width / wf_dist) - 1);
    if (num_wfs <= 0) return {};
    auto planes = ntw_find_planes(mn, width, num_wfs, wf_dist);
    auto sorted = ntw_new_sorted_outlines(outlines);

    std::vector<Outline3D> wfs;
    for (double pv : planes) {
        auto wf = ntw_create_wf_list(sorted, pv, starting_slice * Z_SPACING_FULL, wf_offset);
        if ((int)wf.size() >= 4) wfs.push_back(std::move(wf));
    }
    return wfs;
}

// ============================================================================
// Section 18: Cubic Hermite spline (replaces scipy.interpolate.CubicHermiteSpline)
// ============================================================================

// Only used with exactly 2 knots. Closed-form Hermite basis.
static double hermite_eval(double t0, double t1, double v0, double v1,
                            double d0, double d1, double t) {
    double dt = t1 - t0;
    if (std::abs(dt) < 1e-15) return v0;
    double s = (t - t0) / dt;
    double s2 = s * s, s3 = s2 * s;
    double h00 = 2*s3 - 3*s2 + 1;
    double h10 = (s3 - 2*s2 + s) * dt;
    double h01 = -2*s3 + 3*s2;
    double h11 = (s3 - s2) * dt;
    return h00*v0 + h10*d0 + h01*v1 + h11*d1;
}

// ============================================================================
// Section 19: Kochanek-Bartels spline
// ============================================================================

static std::vector<double> kbs_chord_lengths(Vec2 P0, Vec2 P1, Vec2 P2, Vec2 P3) {
    Vec2 pts[] = {P0, P1, P2, P3};
    std::vector<double> ts = {0};
    for (int i = 1; i < 4; i++)
        ts.push_back(ts.back() + dist2d(pts[i], pts[i-1]));
    return ts;
}

static void kbs_compute_tangent(Vec2 Pp, Vec2 Pc, Vec2 Pn,
                                  double tp, double tc, double tn,
                                  double T, double C, double B, bool outgoing,
                                  double& tx, double& ty) {
    double dt1 = tc - tp, dt2 = tn - tc;
    double d1x = dt1 != 0 ? (Pc.x - Pp.x) / dt1 : 0;
    double d1y = dt1 != 0 ? (Pc.y - Pp.y) / dt1 : 0;
    double d2x = dt2 != 0 ? (Pn.x - Pc.x) / dt2 : 0;
    double d2y = dt2 != 0 ? (Pn.y - Pc.y) / dt2 : 0;

    if (outgoing) {
        double a = (1-T)*(1+C)*(1+B)/2, b = (1-T)*(1-C)*(1-B)/2;
        tx = a*d1x + b*d2x; ty = a*d1y + b*d2y;
    } else {
        double a = (1-T)*(1-C)*(1+B)/2, b = (1-T)*(1+C)*(1-B)/2;
        tx = a*d1x + b*d2x; ty = a*d1y + b*d2y;
    }
}

static std::pair<std::vector<double>, std::vector<double>>
kbs_spline_nonuniform(Vec2 P0, Vec2 P1, Vec2 P2, Vec2 P3,
                       double tension, double continuity, double bias, int num_points) {
    auto ts = kbs_chord_lengths(P0, P1, P2, P3);
    double t0 = ts[0], t1 = ts[1], t2 = ts[2], t3 = ts[3];

    if (std::abs(t2 - t1) < 1e-12) {
        return {std::vector<double>(num_points, P1.x), std::vector<double>(num_points, P1.y)};
    }

    double T1x, T1y, T2x, T2y;
    kbs_compute_tangent(P0, P1, P2, t0, t1, t2, tension, continuity, bias, true, T1x, T1y);
    kbs_compute_tangent(P1, P2, P3, t1, t2, t3, tension, continuity, bias, false, T2x, T2y);

    std::vector<double> us(num_points), vs(num_points);
    for (int i = 0; i < num_points; i++) {
        double t = t1 + (t2 - t1) * i / (num_points - 1);
        us[i] = hermite_eval(t1, t2, P1.x, P2.x, T1x, T2x, t);
        vs[i] = hermite_eval(t1, t2, P1.y, P2.y, T1y, T2y, t);
    }
    return {us, vs};
}

static std::vector<double> kbs_v_for_u(double target_u, Vec2 P0, Vec2 P1, Vec2 P2, Vec2 P3,
                                         double tension, double continuity, double bias, double tol = 1.0) {
    auto [us, vs] = kbs_spline_nonuniform(P0, P1, P2, P3, tension, continuity, bias, 1000);
    std::vector<double> matches;
    for (int i = 0; i < (int)us.size(); i++)
        if (std::abs(us[i] - target_u) < tol)
            matches.push_back(vs[i]);
    return matches;
}

// ============================================================================
// Section 20: Cap finder
// ============================================================================

struct CapArch {
    Outline3D arch;
    Outline3D* xz_outline = nullptr;
    Outline3D* yz_outline = nullptr;
    std::string xz_or_yz;
    std::string top_or_bottom;

    void order_arch() {
        if (xz_or_yz == "XZ")
            std::sort(arch.begin(), arch.end(), [](auto& a, auto& b) { return a.x < b.x; });
        else
            std::sort(arch.begin(), arch.end(), [](auto& a, auto& b) { return a.y < b.y; });
        if (top_or_bottom == "bottom")
            std::reverse(arch.begin(), arch.end());
    }

    Outline3D add_to_outline() {
        Outline3D* wo = xz_or_yz == "XZ" ? xz_outline : yz_outline;
        if (!wo) return {};
        order_arch();
        Outline3D res;
        if (top_or_bottom == "top") {
            int mid = (int)wo->size() / 2;
            res.insert(res.end(), wo->begin(), wo->begin() + mid);
            res.insert(res.end(), arch.begin(), arch.end());
            res.insert(res.end(), wo->begin() + mid, wo->end());
        } else {
            res.insert(res.end(), wo->begin(), wo->end());
            res.insert(res.end(), arch.begin(), arch.end());
        }
        return res;
    }
};

static std::vector<Vec3> cfoa_four_imp_points(const Outline3D& outline, const std::string& tb) {
    if (tb == "top") {
        int mid = (int)outline.size() / 2;
        return {outline[mid-2], outline[mid-1], outline[mid], outline[mid+1]};
    }
    return {outline[outline.size()-2], outline.back(), outline[0], outline[1]};
}

static double cfoa_find_z(const Outline3D& XZ_pts, const Outline3D& YZ_pts,
                            Vec2 intersection, const std::string& tb,
                            double tens, double cont, double bias_v) {
    // XZ: project to (x, z)
    Vec2 xz0 = {XZ_pts[0].x, XZ_pts[0].z}, xz1 = {XZ_pts[1].x, XZ_pts[1].z};
    Vec2 xz2 = {XZ_pts[2].x, XZ_pts[2].z}, xz3 = {XZ_pts[3].x, XZ_pts[3].z};
    auto z1_list = kbs_v_for_u(intersection.x, xz0, xz1, xz2, xz3, tens, cont, bias_v);

    Vec2 yz0 = {YZ_pts[0].y, YZ_pts[0].z}, yz1 = {YZ_pts[1].y, YZ_pts[1].z};
    Vec2 yz2 = {YZ_pts[2].y, YZ_pts[2].z}, yz3 = {YZ_pts[3].y, YZ_pts[3].z};
    auto z2_list = kbs_v_for_u(intersection.y, yz0, yz1, yz2, yz3, tens, cont, bias_v);

    if (z1_list.empty() || z2_list.empty()) return 0;

    double z1, z2;
    if (tb == "top") {
        z1 = *std::max_element(z1_list.begin(), z1_list.end());
        z2 = *std::max_element(z2_list.begin(), z2_list.end());
    } else {
        z1 = *std::min_element(z1_list.begin(), z1_list.end());
        z2 = *std::min_element(z2_list.begin(), z2_list.end());
    }
    return std::min(z1, z2);
}

static std::optional<Vec2> cfoa_find_intersection(const Outline3D& XZ_line, const Outline3D& YZ_line,
                                                    const std::string& tb) {
    auto xz4 = cfoa_four_imp_points(XZ_line, tb);
    auto yz4 = cfoa_four_imp_points(YZ_line, tb);
    // Use middle two points
    double y = xz4[1].y;
    double x1 = xz4[1].x, x2 = xz4[2].x;
    double x = yz4[1].x;
    double y1 = yz4[1].y, y2 = yz4[2].y;

    if (std::min(x1,x2) <= x && x <= std::max(x1,x2) &&
        std::min(y1,y2) <= y && y <= std::max(y1,y2))
        return Vec2{x, y};
    return std::nullopt;
}

static double cfoa_find_min_max_z(const std::vector<Outline3D>& outlines, const std::string& tb) {
    double result = outlines[0][0].z;
    for (auto& o : outlines)
        for (auto& p : o)
            result = tb == "top" ? std::max(result, p.z) : std::min(result, p.z);
    return result;
}

static std::vector<Outline3D*> cfoa_find_cap_outlines(std::vector<Outline3D>& outlines, double cap_lvl) {
    std::vector<Outline3D*> result;
    for (auto& o : outlines)
        for (auto& p : o)
            if (p.z == cap_lvl) { result.push_back(&o); break; }
    return result;
}

static double cfoa_find_limit(const std::vector<Outline3D>& all, const std::string& tb, double cap_lvl) {
    std::vector<double> z_wo;
    for (auto& o : all)
        for (auto& p : o)
            if (p.z != cap_lvl) z_wo.push_back(p.z);
    if (z_wo.empty()) return cap_lvl;
    double second = tb == "top" ? *std::max_element(z_wo.begin(), z_wo.end())
                                : *std::min_element(z_wo.begin(), z_wo.end());
    double dist = std::abs(second - cap_lvl);
    return tb == "top" ? cap_lvl + dist : cap_lvl - dist;
}

struct CapPoint {
    Vec2 intersection;
    double z;
    Vec3 pos;
};

static void cfoa_execute(std::vector<Outline3D>& all_XZ, std::vector<Outline3D>& all_YZ,
                           const std::string& tb, double tens, double cont, double bias_v) {
    if (all_XZ.empty() || all_YZ.empty()) return;

    std::vector<Outline3D> all_combined;
    all_combined.insert(all_combined.end(), all_XZ.begin(), all_XZ.end());
    all_combined.insert(all_combined.end(), all_YZ.begin(), all_YZ.end());
    double cap_lvl = cfoa_find_min_max_z(all_combined, tb);

    auto xz_caps = cfoa_find_cap_outlines(all_XZ, cap_lvl);
    auto yz_caps = cfoa_find_cap_outlines(all_YZ, cap_lvl);

    // Build arches: map outline pointer -> arch points
    std::map<Outline3D*, Outline3D> arches;
    for (auto* p : xz_caps) arches[p] = {};
    for (auto* p : yz_caps) arches[p] = {};

    std::vector<CapPoint> cap_points;
    for (auto* xz : xz_caps) {
        for (auto* yz : yz_caps) {
            auto intersection = cfoa_find_intersection(*xz, *yz, tb);
            if (!intersection) continue;

            auto xz4 = cfoa_four_imp_points(*xz, tb);
            auto yz4 = cfoa_four_imp_points(*yz, tb);
            double z = cfoa_find_z(xz4, yz4, *intersection, tb, tens, cont, bias_v);
            Vec3 pos = {intersection->x, intersection->y, z};
            cap_points.push_back({*intersection, z, pos});
            arches[xz].push_back(pos);
            arches[yz].push_back(pos);
        }
    }

    if (cap_points.empty()) return;

    // Scale cap points
    double limit = cfoa_find_limit(all_combined, tb, cap_lvl);
    double max_z = cap_points[0].z, min_z = cap_points[0].z;
    for (auto& cp : cap_points) {
        max_z = std::max(max_z, cp.z);
        min_z = std::min(min_z, cp.z);
    }

    double scale_factor = 1.0;
    if (tb == "top" && max_z > limit && max_z != cap_lvl)
        scale_factor = std::abs((limit - cap_lvl) / (max_z - cap_lvl));
    else if (tb == "bottom" && min_z < limit && min_z != cap_lvl)
        scale_factor = std::abs((limit - cap_lvl) / (min_z - cap_lvl));

    if (scale_factor != 1.0) {
        for (auto& [ptr, arch] : arches)
            for (auto& p : arch)
                p.z = (p.z - cap_lvl) * scale_factor + cap_lvl;
    }

    // Insert arches into outlines
    auto insert_arch = [&](Outline3D& outline, bool is_xz) {
        auto it = arches.find(&outline);
        if (it == arches.end() || it->second.empty()) return;

        auto& arch = it->second;
        if (is_xz)
            std::sort(arch.begin(), arch.end(), [](auto& a, auto& b) { return a.x < b.x; });
        else
            std::sort(arch.begin(), arch.end(), [](auto& a, auto& b) { return a.y < b.y; });
        if (tb == "bottom") std::reverse(arch.begin(), arch.end());

        Outline3D res;
        if (tb == "top") {
            int mid = (int)outline.size() / 2;
            res.insert(res.end(), outline.begin(), outline.begin() + mid);
            res.insert(res.end(), arch.begin(), arch.end());
            res.insert(res.end(), outline.begin() + mid, outline.end());
        } else {
            res = outline;
            res.insert(res.end(), arch.begin(), arch.end());
        }
        outline = std::move(res);
    };

    for (auto& o : all_XZ) insert_arch(o, true);
    for (auto& o : all_YZ) insert_arch(o, false);
}

// ============================================================================
// Section 21: Catmull-Rom spline injection
// ============================================================================

static std::vector<Vec3> catmull_rom_spline(Vec3 P0, Vec3 P1, Vec3 P2, Vec3 P3, int n_points) {
    std::vector<Vec3> pts;
    for (int i = 1; i <= n_points; i++) {
        double t = (double)i / (n_points + 1);
        double t2 = t * t, t3 = t2 * t;
        double x = 0.5 * ((2*P1.x) + (-P0.x+P2.x)*t + (2*P0.x-5*P1.x+4*P2.x-P3.x)*t2 + (-P0.x+3*P1.x-3*P2.x+P3.x)*t3);
        double y = 0.5 * ((2*P1.y) + (-P0.y+P2.y)*t + (2*P0.y-5*P1.y+4*P2.y-P3.y)*t2 + (-P0.y+3*P1.y-3*P2.y+P3.y)*t3);
        double z = 0.5 * ((2*P1.z) + (-P0.z+P2.z)*t + (2*P0.z-5*P1.z+4*P2.z-P3.z)*t2 + (-P0.z+3*P1.z-3*P2.z+P3.z)*t3);
        pts.push_back({x, y, z});
    }
    return pts;
}

static Outline3D inject_catmull_rom(const Outline3D& pts, int pps, bool top_spline = true) {
    double max_z = pts[0].z, min_z = pts[0].z;
    for (auto& p : pts) { max_z = std::max(max_z, p.z); min_z = std::min(min_z, p.z); }

    int n = (int)pts.size();
    Outline3D result;
    for (int i = 0; i < n; i++) {
        auto P0 = pts[((i - 1) % n + n) % n];
        auto P1 = pts[i];
        auto P2 = pts[(i + 1) % n];
        auto P3 = pts[(i + 2) % n];
        result.push_back(P1);

        if (!top_spline && ((P1.z == max_z && P2.z == max_z) || (P1.z == min_z && P2.z == min_z)))
            continue;

        auto extra = catmull_rom_spline(P0, P1, P2, P3, pps);
        result.insert(result.end(), extra.begin(), extra.end());
    }
    return result;
}

// ============================================================================
// Section 22: Cell point filler
// ============================================================================

static Outline3D spline_and_circuit(const Outline3D& wf, int pps, bool top_spline, bool spline) {
    Outline3D res = spline ? inject_catmull_rom(wf, pps, top_spline) : wf;
    res.push_back(res[0]);
    res.push_back(res[1]);
    res.push_back(res[2]);
    return res;
}

static std::pair<std::vector<Outline3D>, std::vector<Outline3D>>
cpf_point_filler(const Cell& cell, double tens, double cont, double bias_v,
                  int pps, bool top_spline = true, bool spline = true) {
    double wf_dist = Z_SPACING_FULL / 5.0;
    double wf_offset = 1.5;

    auto wfsx = ntw_triple_wireframe_creation(cell.outlines, 0, cell.starting_slice, wf_dist, wf_offset);
    auto wfsy = ntw_triple_wireframe_creation(cell.outlines, 1, cell.starting_slice, wf_dist, wf_offset);

    if (!spline) {
        std::vector<Outline3D> rx, ry;
        for (auto& w : wfsx) rx.push_back(spline_and_circuit(w, pps, top_spline, false));
        for (auto& w : wfsy) ry.push_back(spline_and_circuit(w, pps, top_spline, false));
        return {rx, ry};
    }

    // Top cap
    cfoa_execute(wfsy, wfsx, "top", tens, cont, bias_v);
    // Bottom cap
    cfoa_execute(wfsy, wfsx, "bottom", tens, cont, bias_v);

    std::vector<Outline3D> rx, ry;
    for (auto& w : wfsy) rx.push_back(spline_and_circuit(w, pps, top_spline, true));
    for (auto& w : wfsx) ry.push_back(spline_and_circuit(w, pps, top_spline, true));
    return {rx, ry};
}

// ============================================================================
// Section 23: Contour stitching mesh
// ============================================================================

static std::vector<Vec2> resample_outline(const Outline2D& outline, int num_points) {
    if (outline.empty()) return std::vector<Vec2>(num_points, {0, 0});

    // Close the contour
    Outline2D pts = outline;
    pts.push_back(pts[0]);

    std::vector<double> cum = {0};
    for (size_t i = 1; i < pts.size(); i++)
        cum.push_back(cum.back() + dist2d(pts[i-1], pts[i]));
    double total = cum.back();
    if (total == 0) return std::vector<Vec2>(num_points, pts[0]);

    std::vector<Vec2> resampled(num_points);
    for (int i = 0; i < num_points; i++) {
        double target = total * i / num_points;
        auto it = std::upper_bound(cum.begin(), cum.end(), target);
        int idx = std::max(0, (int)(it - cum.begin()) - 1);
        idx = std::min(idx, (int)cum.size() - 2);
        double seg_len = cum[idx+1] - cum[idx];
        double frac = seg_len > 0 ? (target - cum[idx]) / seg_len : 0;
        resampled[i] = {pts[idx].x * (1-frac) + pts[idx+1].x * frac,
                        pts[idx].y * (1-frac) + pts[idx+1].y * frac};
    }
    return resampled;
}

static Outline2D ensure_ccw(const Outline2D& outline) {
    double area = 0;
    int n = (int)outline.size();
    for (int i = 0; i < n; i++) {
        int j = (i + 1) % n;
        area += outline[i].x * outline[j].y - outline[j].x * outline[i].y;
    }
    if (area < 0) {
        Outline2D rev(outline.rbegin(), outline.rend());
        return rev;
    }
    return outline;
}

static Outline2D align_start(const Outline2D& ref, const Outline2D& target) {
    double best_dist = std::numeric_limits<double>::max();
    int best_idx = 0;
    for (int i = 0; i < (int)target.size(); i++) {
        double d = distance_sq(target[i], ref[0]);
        if (d < best_dist) { best_dist = d; best_idx = i; }
    }
    Outline2D result;
    for (int i = 0; i < (int)target.size(); i++)
        result.push_back(target[(i + best_idx) % target.size()]);
    return result;
}

static Outline2D smooth_contour(const Outline2D& contour, int iterations, double factor = 0.5) {
    auto pts = contour;
    int n = (int)pts.size();
    for (int iter = 0; iter < iterations; iter++) {
        Outline2D next(n);
        for (int i = 0; i < n; i++) {
            auto& prev = pts[((i-1)%n+n)%n];
            auto& nxt = pts[(i+1)%n];
            next[i] = {pts[i].x + factor * (0.5*(prev.x+nxt.x) - pts[i].x),
                       pts[i].y + factor * (0.5*(prev.y+nxt.y) - pts[i].y)};
        }
        pts = next;
    }
    return pts;
}

static Outline2D slice_wireframes_at_z(const std::vector<Outline3D>& all_wf, double z_target) {
    Outline2D crossings;
    for (auto& loop : all_wf) {
        if ((int)loop.size() < 4) continue;
        int n_seg = (int)loop.size() - 3;
        for (int i = 0; i < n_seg; i++) {
            double z0 = loop[i].z, z1 = loop[i+1].z;
            double dz = z1 - z0;
            if (std::abs(dz) < 1e-9) continue;
            if ((z0 - z_target) * (z1 - z_target) < 0) {
                double t = (z_target - z0) / dz;
                crossings.push_back({
                    loop[i].x + t * (loop[i+1].x - loop[i].x),
                    loop[i].y + t * (loop[i+1].y - loop[i].y)
                });
            }
        }
    }
    return crossings;
}

static Outline2D crossings_to_contour(const Outline2D& crossings, int num_points) {
    Vec2 centroid = find_center_2d(crossings);
    // Sort by angle
    std::vector<std::pair<double, int>> angles;
    for (int i = 0; i < (int)crossings.size(); i++)
        angles.push_back({std::atan2(crossings[i].y - centroid.y, crossings[i].x - centroid.x), i});
    std::sort(angles.begin(), angles.end());

    Outline2D sorted;
    for (auto& [a, i] : angles) sorted.push_back(crossings[i]);
    return resample_outline(sorted, num_points);
}

static std::optional<TriMesh> mesh_from_wireframes(
    const std::vector<Outline3D>& splined_xz, const std::vector<Outline3D>& splined_yz,
    const std::vector<Outline2D>& outlines, int starting_slice,
    double z_scale = Z_SPACING_FULL, int num_points = MESH_NUM_POINTS,
    int interp_per_gap = INTERP_PER_GAP, int num_cap_levels = NUM_CAP_LEVELS,
    int smooth_iters = MESH_SMOOTH_ITERS)
{
    std::vector<Outline3D> all_wf;
    all_wf.insert(all_wf.end(), splined_xz.begin(), splined_xz.end());
    all_wf.insert(all_wf.end(), splined_yz.begin(), splined_yz.end());

    if (all_wf.empty() || outlines.size() < 2) return std::nullopt;

    double wf_z_min = all_wf[0][0].z, wf_z_max = all_wf[0][0].z;
    for (auto& loop : all_wf)
        for (auto& p : loop) {
            wf_z_min = std::min(wf_z_min, p.z);
            wf_z_max = std::max(wf_z_max, p.z);
        }

    int num_slices = (int)outlines.size();
    std::vector<double> orig_zs(num_slices);
    for (int i = 0; i < num_slices; i++) orig_zs[i] = (starting_slice + i) * z_scale;

    // Process original contours
    std::vector<Outline2D> orig_contours(num_slices);
    std::vector<Vec2> centroids(num_slices);
    for (int i = 0; i < num_slices; i++) {
        auto pts = ensure_ccw(outlines[i]);
        auto contour = resample_outline(pts, num_points);
        if (smooth_iters > 0) contour = smooth_contour(contour, smooth_iters);
        centroids[i] = find_center_2d(contour);
        // Center contour
        for (auto& p : contour) { p.x -= centroids[i].x; p.y -= centroids[i].y; }
        orig_contours[i] = contour;
    }
    for (int i = 1; i < num_slices; i++)
        orig_contours[i] = align_start(orig_contours[i-1], orig_contours[i]);

    // Build z_plan
    struct ZPlanEntry { double z; int type; int idx; int idx_b; double frac; };
    // type: 0=original, 1=body, 2=wireframe
    std::vector<ZPlanEntry> z_plan;

    double bot_range = orig_zs[0] - wf_z_min;
    if (bot_range > 0) {
        for (int i = 1; i <= num_cap_levels; i++) {
            double frac = (double)i / (num_cap_levels + 1);
            z_plan.push_back({wf_z_min + frac * bot_range, 2, 0, 0, 0});
        }
    }

    for (int i = 0; i < num_slices; i++) {
        z_plan.push_back({orig_zs[i], 0, i, 0, 0});
        if (i < num_slices - 1) {
            double gap = orig_zs[i+1] - orig_zs[i];
            for (int j = 1; j <= interp_per_gap; j++) {
                double frac = (double)j / (interp_per_gap + 1);
                z_plan.push_back({orig_zs[i] + frac * gap, 1, i, i+1, frac});
            }
        }
    }

    double top_range = wf_z_max - orig_zs[num_slices - 1];
    if (top_range > 0) {
        for (int i = 1; i <= num_cap_levels; i++) {
            double frac = (double)i / (num_cap_levels + 1);
            z_plan.push_back({orig_zs[num_slices-1] + frac * top_range, 2, 0, 0, 0});
        }
    }

    std::sort(z_plan.begin(), z_plan.end(), [](auto& a, auto& b) { return a.z < b.z; });

    // Build contour levels
    std::vector<std::pair<double, Outline2D>> contours;
    for (auto& entry : z_plan) {
        if (entry.type == 0) { // original
            Outline2D c = orig_contours[entry.idx];
            for (int j = 0; j < num_points; j++) {
                c[j].x += centroids[entry.idx].x;
                c[j].y += centroids[entry.idx].y;
            }
            contours.push_back({entry.z, c});
        } else if (entry.type == 1) { // body (Catmull-Rom interpolation)
            int ia = entry.idx, ib = entry.idx_b;
            double t = entry.frac, t2 = t*t, t3 = t2*t;
            auto& P1 = orig_contours[ia];
            auto& P2 = orig_contours[ib];
            auto& P0 = ia > 0 ? orig_contours[ia-1] : P1;
            auto& P3 = ib < num_slices-1 ? orig_contours[ib+1] : P2;

            Outline2D shape(num_points);
            for (int j = 0; j < num_points; j++) {
                shape[j].x = 0.5 * ((2*P1[j].x) + (-P0[j].x+P2[j].x)*t +
                    (2*P0[j].x-5*P1[j].x+4*P2[j].x-P3[j].x)*t2 +
                    (-P0[j].x+3*P1[j].x-3*P2[j].x+P3[j].x)*t3);
                shape[j].y = 0.5 * ((2*P1[j].y) + (-P0[j].y+P2[j].y)*t +
                    (2*P0[j].y-5*P1[j].y+4*P2[j].y-P3[j].y)*t2 +
                    (-P0[j].y+3*P1[j].y-3*P2[j].y+P3[j].y)*t3);
            }
            Vec2 center = {(1-t)*centroids[ia].x + t*centroids[ib].x,
                           (1-t)*centroids[ia].y + t*centroids[ib].y};
            for (auto& p : shape) { p.x += center.x; p.y += center.y; }
            contours.push_back({entry.z, shape});
        } else { // wireframe
            auto crossings = slice_wireframes_at_z(all_wf, entry.z);
            if ((int)crossings.size() < 4) continue;
            auto contour = crossings_to_contour(crossings, num_points);
            if (smooth_iters > 0) contour = smooth_contour(contour, smooth_iters);
            contours.push_back({entry.z, contour});
        }
    }

    if ((int)contours.size() < 2) return std::nullopt;

    // Align all contours
    for (int i = 1; i < (int)contours.size(); i++)
        contours[i].second = align_start(contours[i-1].second, contours[i].second);

    // Build mesh
    TriMesh mesh;
    int n = num_points;

    for (auto& [z, contour] : contours)
        for (auto& pt : contour)
            mesh.vertices.push_back({pt.x, pt.y, z});

    for (int i = 0; i < (int)contours.size() - 1; i++) {
        int a = i * n, b = (i + 1) * n;
        for (int j = 0; j < n; j++) {
            int nj = (j + 1) % n;
            mesh.faces.push_back({a+j, b+j, a+nj});
            mesh.faces.push_back({a+nj, b+j, b+nj});
        }
    }

    // Bottom cap
    auto& bot = contours[0].second;
    Vec2 bot_center = find_center_2d(bot);
    int bot_idx = (int)mesh.vertices.size();
    mesh.vertices.push_back({bot_center.x, bot_center.y, wf_z_min});
    for (int j = 0; j < n; j++)
        mesh.faces.push_back({j, (j+1)%n, bot_idx});

    // Top cap
    int last_off = ((int)contours.size() - 1) * n;
    auto& top = contours.back().second;
    Vec2 top_center = find_center_2d(top);
    int top_idx = (int)mesh.vertices.size();
    mesh.vertices.push_back({top_center.x, top_center.y, wf_z_max});
    for (int j = 0; j < n; j++)
        mesh.faces.push_back({last_off + (j+1)%n, last_off + j, top_idx});

    mesh.fix_normals();
    return mesh;
}

// ============================================================================
// Section 24: Fallback mesh from contours
// ============================================================================

static std::optional<TriMesh> mesh_from_contours(
    const std::vector<Outline2D>& outlines, int starting_slice,
    int num_points = CONTOUR_NUM_POINTS, double z_scale = Z_SPACING_FULL,
    int smooth_iters = CONTOUR_SMOOTH_ITERS)
{
    if ((int)outlines.size() < 2) return std::nullopt;

    std::vector<Outline2D> resampled;
    for (auto& o : outlines) {
        auto pts = ensure_ccw(o);
        auto contour = resample_outline(pts, num_points);
        if (smooth_iters > 0) contour = smooth_contour(contour, smooth_iters);
        resampled.push_back(contour);
    }
    for (int i = 1; i < (int)resampled.size(); i++)
        resampled[i] = align_start(resampled[i-1], resampled[i]);

    TriMesh mesh;
    int n = num_points;

    for (int i = 0; i < (int)resampled.size(); i++) {
        double z = (starting_slice + i) * z_scale;
        for (auto& pt : resampled[i])
            mesh.vertices.push_back({pt.x, pt.y, z});
    }

    for (int i = 0; i < (int)resampled.size() - 1; i++) {
        int a = i * n, b = (i + 1) * n;
        for (int j = 0; j < n; j++) {
            int nj = (j + 1) % n;
            mesh.faces.push_back({a+j, b+j, a+nj});
            mesh.faces.push_back({a+nj, b+j, b+nj});
        }
    }

    double dome_height = z_scale;

    // Bottom dome
    auto& bot = resampled[0];
    Vec2 bot_center = find_center_2d(bot);
    double bot_z = starting_slice * z_scale;
    int bot_ring_off = (int)mesh.vertices.size();
    for (int j = 0; j < n; j++) {
        double x = bot_center.x + 0.5 * (bot[j].x - bot_center.x);
        double y = bot_center.y + 0.5 * (bot[j].y - bot_center.y);
        mesh.vertices.push_back({x, y, bot_z - 0.5 * dome_height});
    }
    for (int j = 0; j < n; j++) {
        int nj = (j + 1) % n;
        mesh.faces.push_back({j, nj, bot_ring_off + j});
        mesh.faces.push_back({nj, bot_ring_off + nj, bot_ring_off + j});
    }
    int bot_cidx = (int)mesh.vertices.size();
    mesh.vertices.push_back({bot_center.x, bot_center.y, bot_z - dome_height});
    for (int j = 0; j < n; j++)
        mesh.faces.push_back({bot_ring_off + j, bot_ring_off + (j+1)%n, bot_cidx});

    // Top dome
    auto& top = resampled.back();
    Vec2 top_center = find_center_2d(top);
    double top_z = (starting_slice + (int)resampled.size() - 1) * z_scale;
    int top_off = ((int)resampled.size() - 1) * n;
    int top_ring_off = (int)mesh.vertices.size();
    for (int j = 0; j < n; j++) {
        double x = top_center.x + 0.5 * (top[j].x - top_center.x);
        double y = top_center.y + 0.5 * (top[j].y - top_center.y);
        mesh.vertices.push_back({x, y, top_z + 0.5 * dome_height});
    }
    for (int j = 0; j < n; j++) {
        int nj = (j + 1) % n;
        mesh.faces.push_back({top_off + nj, top_off + j, top_ring_off + j});
        mesh.faces.push_back({top_off + nj, top_ring_off + j, top_ring_off + nj});
    }
    int top_cidx = (int)mesh.vertices.size();
    mesh.vertices.push_back({top_center.x, top_center.y, top_z + dome_height});
    for (int j = 0; j < n; j++)
        mesh.faces.push_back({top_ring_off + j, top_cidx, top_ring_off + (j+1)%n});

    mesh.fix_normals();
    return mesh;
}

// ============================================================================
// Section 25: Quantification
// ============================================================================

struct OptVec3 {
    bool valid = false;
    Vec3 val;
};

static std::vector<OptVec3> get_positions(const Cell3D& cell, int num_tps) {
    std::vector<OptVec3> res(num_tps, {false, {}});
    for (int i = 0; i < (int)cell.centers3D.size(); i++)
        res[cell.starting_tp + i] = {true, cell.centers3D[i]};
    return res;
}

static std::vector<OptVec3> get_displacement_vecs(const std::vector<OptVec3>& positions) {
    std::vector<OptVec3> res(positions.size(), {false, {}});
    for (int i = 1; i < (int)positions.size(); i++) {
        if (positions[i-1].valid && positions[i].valid) {
            res[i] = {true, {positions[i].val.x - positions[i-1].val.x,
                             positions[i].val.y - positions[i-1].val.y,
                             positions[i].val.z - positions[i-1].val.z}};
        }
    }
    return res;
}

static std::vector<double> get_distances(const std::vector<OptVec3>& displacements) {
    std::vector<double> res(displacements.size(), -1);
    for (int i = 0; i < (int)displacements.size(); i++) {
        if (displacements[i].valid) {
            auto& d = displacements[i].val;
            res[i] = std::sqrt(d.x*d.x + d.y*d.y + d.z*d.z);
        }
    }
    return res;
}

static std::vector<std::optional<TriMesh>> get_solid_mesh_objs(const Cell3D& cell, int num_tps) {
    std::vector<std::optional<TriMesh>> meshes(num_tps, std::nullopt);

    for (int i = 0; i < (int)cell.cells_list.size(); i++) {
        int tp = cell.starting_tp + i;
        auto& c = cell.cells_list[i];
        if (c.outlines.size() <= 1) continue;

        std::vector<Outline3D> sx, sy;
        try {
            auto [xz, yz] = cpf_point_filler(c, TENSION, CONTINUITY, BIAS, POINTS_PER_SEGMENT);
            sx = std::move(xz);
            sy = std::move(yz);
        } catch (...) {}

        std::optional<TriMesh> mesh;
        if ((int)(sx.size() + sy.size()) >= 4) {
            mesh = mesh_from_wireframes(sx, sy, c.outlines, c.starting_slice);
        } else {
            std::cout << "Can't spline correctly  ";
            mesh = mesh_from_contours(c.outlines, c.starting_slice);
        }

        if (mesh) std::cout << "Created mesh, " << mesh->vertices.size() << " vertices\n";
        meshes[tp] = std::move(mesh);
    }
    return meshes;
}

// ============================================================================
// Section 26: CSV export
// ============================================================================

static std::string fmt_opt_tuple(const OptVec3& v, int places) {
    if (!v.valid) return "";
    return "(" + std::to_string(round_num(v.val.x, places)) + ", " +
                 std::to_string(round_num(v.val.y, places)) + ", " +
                 std::to_string(round_num(v.val.z, places)) + ")";
}

static std::string fmt_opt_num(double v, int places) {
    if (v < 0) return "";
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(places) << round_num(v, places);
    return ss.str();
}

static void export_csv(const std::vector<Cell3D>& cells,
                        const std::vector<std::vector<std::optional<TriMesh>>>& all_meshes,
                        const std::string& path, int num_tps) {
    std::ofstream out(path);
    out << "Cell ID,Timepoint,Position,X Pos,Y Pos,Z Pos,"
        << "Displacement Vector,X Disp,Y Disp,Z Disp,"
        << "Distance Traveled,Volume,Surface Area\n";

    for (int ci = 0; ci < (int)cells.size(); ci++) {
        auto& cell = cells[ci];
        auto positions = get_positions(cell, num_tps);
        auto displacements = get_displacement_vecs(positions);
        auto distances = get_distances(displacements);
        auto& meshes = all_meshes[ci];

        // Cell ID header row
        out << cell.id << "\n";

        for (int t = 0; t < num_tps; t++) {
            out << ","; // Cell ID empty for data rows
            out << t << ",";
            out << fmt_opt_tuple(positions[t], ROUND_DECIMAL_PLACE) << ",";
            if (positions[t].valid) {
                out << fmt_opt_num(positions[t].val.x, ROUND_DECIMAL_PLACE) << ","
                    << fmt_opt_num(positions[t].val.y, ROUND_DECIMAL_PLACE) << ","
                    << fmt_opt_num(positions[t].val.z, ROUND_DECIMAL_PLACE) << ",";
            } else {
                out << ",,,";
            }
            out << fmt_opt_tuple(displacements[t], ROUND_DECIMAL_PLACE) << ",";
            if (displacements[t].valid) {
                out << fmt_opt_num(displacements[t].val.x, ROUND_DECIMAL_PLACE) << ","
                    << fmt_opt_num(displacements[t].val.y, ROUND_DECIMAL_PLACE) << ","
                    << fmt_opt_num(displacements[t].val.z, ROUND_DECIMAL_PLACE) << ",";
            } else {
                out << ",,,";
            }
            out << (distances[t] >= 0 ? fmt_opt_num(distances[t], ROUND_DECIMAL_PLACE) : "") << ",";

            if (meshes[t]) {
                out << fmt_opt_num(meshes[t]->volume(), ROUND_DECIMAL_PLACE) << ","
                    << fmt_opt_num(meshes[t]->surface_area(), ROUND_DECIMAL_PLACE);
            } else {
                out << ",";
            }
            out << "\n";
        }
    }
    std::cout << "Exported CSV to " << path << "\n";
}

// ============================================================================
// Section 27: Mesh pickle export
// ============================================================================

static void export_mesh_pickle(const std::vector<Cell3D>& cells,
                                 const std::vector<std::vector<std::optional<TriMesh>>>& all_meshes,
                                 const std::string& path, int num_tps) {
    PklValue mesh_dict = PklValue::dict();

    // Ensure all timepoints exist
    for (int t = 0; t < num_tps; t++) {
        bool found = false;
        for (auto& [k, v] : mesh_dict.dict_items)
            if (k.ival == t) { found = true; break; }
        if (!found)
            mesh_dict.dict_items.emplace_back(PklValue::integer(t), PklValue::list());
    }

    for (int ci = 0; ci < (int)cells.size(); ci++) {
        auto& meshes = all_meshes[ci];
        for (int t = 0; t < num_tps; t++) {
            if (!meshes[t]) continue;
            auto& m = *meshes[t];

            PklValue mesh_obj = PklValue::dict();

            // vertices
            PklValue verts = PklValue::list();
            for (auto& v : m.vertices) {
                PklValue pt = PklValue::list();
                pt.items.push_back(PklValue::floating(v.x));
                pt.items.push_back(PklValue::floating(v.y));
                pt.items.push_back(PklValue::floating(v.z));
                verts.items.push_back(std::move(pt));
            }
            mesh_obj.dict_items.emplace_back(PklValue::string("vertices"), std::move(verts));

            // faces
            PklValue faces = PklValue::list();
            for (auto& f : m.faces) {
                PklValue tri = PklValue::list();
                tri.items.push_back(PklValue::integer(f[0]));
                tri.items.push_back(PklValue::integer(f[1]));
                tri.items.push_back(PklValue::integer(f[2]));
                faces.items.push_back(std::move(tri));
            }
            mesh_obj.dict_items.emplace_back(PklValue::string("faces"), std::move(faces));

            // color
            mesh_obj.dict_items.emplace_back(PklValue::string("color"), color3_to_pkl(cells[ci].color));

            // name
            mesh_obj.dict_items.emplace_back(PklValue::string("name"),
                PklValue::string("cell_" + std::to_string(ci) + "_t" + std::to_string(t)));

            // Add to dict
            for (auto& [k, v] : mesh_dict.dict_items) {
                if (k.ival == t) {
                    v.items.push_back(std::move(mesh_obj));
                    break;
                }
            }
        }
    }

    write_header_pickle(path, "MESH", mesh_dict);
    std::cout << "Exported mesh pickle to " << path << "\n";
}

// ============================================================================
// Section 28: Tracer pickle export
// ============================================================================

static void export_tracers(const std::vector<Cell3D>& cells, const std::string& path, int num_tps) {
    PklValue tracers = PklValue::dict();

    for (auto& cell : cells) {
        PklValue color_key = color3_to_pkl(cell.color);
        auto positions = get_positions(cell, num_tps);

        PklValue trajectory = PklValue::list();
        for (auto& pos : positions) {
            if (!pos.valid) continue;
            PklValue pt = PklValue::tuple();
            pt.items.push_back(PklValue::floating(pos.val.x));
            pt.items.push_back(PklValue::floating(pos.val.y));
            pt.items.push_back(PklValue::floating(pos.val.z));
            trajectory.items.push_back(std::move(pt));
        }

        // Find or create entry for this color
        bool found = false;
        for (auto& [k, v] : tracers.dict_items) {
            if (k == color_key) {
                v.items.push_back(std::move(trajectory));
                found = true;
                break;
            }
        }
        if (!found) {
            PklValue traj_list = PklValue::list();
            traj_list.items.push_back(std::move(trajectory));
            tracers.dict_items.emplace_back(std::move(color_key), std::move(traj_list));
        }
    }

    write_header_pickle(path, "TRACER", tracers);
    std::cout << "Exported tracers to " << path << "\n";
}

// ============================================================================
// Section 29: Outlines-to-wireframe pipeline
// ============================================================================

static Color3 parse_rgb(const std::string& text) {
    int r, g, b;
    if (sscanf(text.c_str(), "%d,%d,%d", &r, &g, &b) != 3)
        throw std::runtime_error("Expected R,G,B format: " + text);
    return {r, g, b};
}

static std::pair<int,int> parse_dims(const std::string& text) {
    int w, h;
    if (sscanf(text.c_str(), "%d,%d", &w, &h) != 2)
        throw std::runtime_error("Expected W,H format: " + text);
    return {w, h};
}

static void outlines_to_wireframe(const fs::path& outlines_dir, const fs::path& wireframe_pkl,
                                    bool skip_lex, const std::string& image_dims_str,
                                    bool find_ref, const std::string& ref_color_str,
                                    bool rotate) {
    if (!skip_lex) {
        std::cout << "Running lexographic renaming\n";
        run_lex_renaming(outlines_dir);
    }

    int width, height;
    if (!image_dims_str.empty()) {
        auto [w, h] = parse_dims(image_dims_str);
        width = w; height = h;
    } else {
        auto dims = find_image_dimensions(outlines_dir);
        width = dims[0]; height = dims[1];
    }

    // Build ref/rot lists
    std::vector<fs::path> tp_dirs;
    for (auto& e : fs::directory_iterator(outlines_dir))
        if (e.is_directory()) tp_dirs.push_back(e.path());
    std::sort(tp_dirs.begin(), tp_dirs.end());
    int n_tps = (int)tp_dirs.size();

    std::vector<std::vector<int>> ref_list(n_tps, {0, 0});
    std::vector<std::vector<int>> rot_list(n_tps, {1, 0});

    if (find_ref) {
        Color3 ref_color = parse_rgb(ref_color_str);
        ref_list = find_ref_points(outlines_dir, ref_color, width, height);
    }

    auto t0 = std::chrono::steady_clock::now();
    auto fd = prepare_manual_data(outlines_dir, ref_list, rot_list, width, height, rotate);
    auto t1 = std::chrono::steady_clock::now();
    double secs = std::chrono::duration<double>(t1 - t0).count();
    std::cout << "\nManual data formatting time: " << secs << "s\n";

    fs::create_directories(wireframe_pkl.parent_path());
    auto pkl_val = frame_dict_to_pkl(fd);
    write_header_pickle(wireframe_pkl.string(), "WIREFRAME", pkl_val);
    std::cout << "Wireframe pickle written: " << wireframe_pkl << "\n";
}

// ============================================================================
// Section 30: Full quantification pipeline
// ============================================================================

static void run_quantification(const fs::path& wireframe_pkl,
                                 const fs::path& tracers_out,
                                 const fs::path& quant_out,
                                 const fs::path& meshes_out,
                                 int skip_slice) {
    std::cout << "Extracting colors from wireframe pickle\n";
    auto [header, pkl_data] = read_header_pickle(wireframe_pkl.string());
    auto fd = pkl_to_frame_dict(pkl_data);
    auto colors = extract_colors(fd, skip_slice);
    std::cout << "Extracted " << colors.size() << " colors\n";

    if (colors.empty())
        throw std::runtime_error("No colors extracted from wireframe pickle.");

    auto cells3d = get_cells3D(fd, colors);
    int num_tps = (int)fd.size();

    std::cout << "Tracers\n";
    fs::create_directories(tracers_out.parent_path());
    export_tracers(cells3d, tracers_out.string(), num_tps);

    std::cout << "Computing meshes\n";
    std::vector<std::vector<std::optional<TriMesh>>> all_meshes;
    for (auto& cell : cells3d)
        all_meshes.push_back(get_solid_mesh_objs(cell, num_tps));

    std::cout << "CSV data\n";
    fs::create_directories(quant_out.parent_path());
    export_csv(cells3d, all_meshes, quant_out.string(), num_tps);

    std::cout << "Meshes\n";
    fs::create_directories(meshes_out.parent_path());
    export_mesh_pickle(cells3d, all_meshes, meshes_out.string(), num_tps);

    std::cout << "Quantification complete\n";
}

// ============================================================================
// Section 31: Flamegraph profiling
// ============================================================================

static void run_with_perf_flamegraph(const std::string& output_svg,
                                       int argc, char** argv) {
    // Re-exec under perf record, then post-process to flamegraph SVG
    std::string self = argv[0];

    // Build child args (strip profiling flags)
    std::vector<std::string> child_args;
    child_args.push_back(self);
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--profile-flamegraph") {
            i++; // skip value
            continue;
        }
        if (arg.find("--profile-flamegraph=") == 0) continue;
        if (arg == "--_profiled-run") continue;
        child_args.push_back(arg);
    }
    child_args.push_back("--_profiled-run");

    // Build perf command
    std::string perf_data = "/tmp/biovision_perf.data";
    std::string cmd = "perf record -g --call-graph dwarf -o " + perf_data + " -- ";
    for (auto& a : child_args) cmd += "'" + a + "' ";

    std::cout << "Running under perf record...\n";
    int ret = std::system(cmd.c_str());
    if (ret != 0) {
        std::cerr << "perf record failed (exit " << ret << "). Is perf installed?\n";
        return;
    }

    // Post-process
    std::string script_cmd = "perf script -i " + perf_data +
        " | stackcollapse-perf.pl | flamegraph.pl > " + output_svg;
    ret = std::system(script_cmd.c_str());
    if (ret != 0) {
        // Try without FlameGraph tools
        std::string alt = "perf script -i " + perf_data + " > " + output_svg + ".perf_script";
        if (std::system(alt.c_str()) != 0) {}
        std::cerr << "FlameGraph tools not found. Raw perf script written to " << output_svg << ".perf_script\n";
        std::cerr << "Install FlameGraph: git clone https://github.com/brendangregg/FlameGraph\n";
    } else {
        std::cout << "Flamegraph written: " << output_svg << "\n";
    }
}

// ============================================================================
// Section 32: CLI parser + main
// ============================================================================

struct Args {
    std::string mode = "existing";
    std::string wireframe_pkl = "./output/wireframe.pkl";
    bool run_quant = false;
    std::string profile_flamegraph;
    bool profiled_run = false;

    std::string tracers_output;
    std::string quant_output;
    std::string meshes_output;
    int skip_slice = 0;

    std::string outlines_dir;
    bool skip_lex = false;
    std::string image_dims;
    bool find_ref = false;
    std::string ref_color = "255,255,0";
    bool rotate = false;
};

static void print_usage() {
    std::cout << "Usage: biovision_pipeline [options]\n\n"
              << "Modes:\n"
              << "  --mode existing   Use existing wireframe .pkl (default)\n"
              << "  --mode outlines   Generate wireframe from outline images\n\n"
              << "Options:\n"
              << "  --wireframe-pkl PATH      Wireframe pickle path\n"
              << "  --run-quant               Run quantification after wireframe\n"
              << "  --profile-flamegraph PATH Generate flamegraph SVG via perf\n"
              << "  --tracers-output PATH     Tracers output path\n"
              << "  --quant-output PATH       Quant CSV output path\n"
              << "  --meshes-output PATH      Meshes pickle output path\n"
              << "  --skip-slice N            Skip N edge slices in color extraction\n"
              << "  --outlines-dir PATH       Outline images directory (outlines mode)\n"
              << "  --skip-lexographic-renaming  Skip file renaming\n"
              << "  --image-dims W,H          Override image dimensions\n"
              << "  --find-reference-points   Detect reference markers\n"
              << "  --reference-point-color R,G,B  Reference marker color\n"
              << "  --rotate                  Enable rotation correction\n";
}

static Args parse_args(int argc, char** argv) {
    Args args;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) throw std::runtime_error("Missing value for " + arg);
            return argv[++i];
        };

        if (arg == "--mode") args.mode = next();
        else if (arg == "--wireframe-pkl") args.wireframe_pkl = next();
        else if (arg == "--run-quant") args.run_quant = true;
        else if (arg == "--profile-flamegraph") args.profile_flamegraph = next();
        else if (arg == "--_profiled-run") args.profiled_run = true;
        else if (arg == "--tracers-output") args.tracers_output = next();
        else if (arg == "--quant-output") args.quant_output = next();
        else if (arg == "--meshes-output") args.meshes_output = next();
        else if (arg == "--skip-slice") args.skip_slice = std::stoi(next());
        else if (arg == "--outlines-dir") args.outlines_dir = next();
        else if (arg == "--skip-lexographic-renaming") args.skip_lex = true;
        else if (arg == "--image-dims") args.image_dims = next();
        else if (arg == "--find-reference-points") args.find_ref = true;
        else if (arg == "--reference-point-color") args.ref_color = next();
        else if (arg == "--rotate") args.rotate = true;
        else if (arg == "--help" || arg == "-h") { print_usage(); std::exit(0); }
        else { std::cerr << "Unknown argument: " << arg << "\n"; print_usage(); std::exit(1); }
    }
    return args;
}

int main(int argc, char** argv) {
    try {
        auto args = parse_args(argc, argv);

        // Profiling re-exec
        if (!args.profile_flamegraph.empty() && !args.profiled_run) {
            run_with_perf_flamegraph(args.profile_flamegraph, argc, argv);
            return 0;
        }

        fs::path wireframe_pkl = fs::absolute(args.wireframe_pkl);

        if (args.mode == "existing") {
            if (!fs::exists(wireframe_pkl))
                throw std::runtime_error("Wireframe pkl not found: " + wireframe_pkl.string());
        } else if (args.mode == "outlines") {
            if (args.outlines_dir.empty())
                throw std::runtime_error("--outlines-dir required in outlines mode");
            outlines_to_wireframe(fs::absolute(args.outlines_dir), wireframe_pkl,
                                   args.skip_lex, args.image_dims,
                                   args.find_ref, args.ref_color, args.rotate);
        } else {
            throw std::runtime_error("Unknown mode: " + args.mode +
                " (C++ version supports 'existing' and 'outlines' only)");
        }

        std::cout << "Wireframe ready: " << wireframe_pkl << "\n";

        if (args.run_quant) {
            fs::path stem = wireframe_pkl.stem();
            fs::path parent = wireframe_pkl.parent_path();

            fs::path tracers = args.tracers_output.empty()
                ? parent / (stem.string() + " TRACERS.pkl") : fs::absolute(args.tracers_output);
            fs::path quant = args.quant_output.empty()
                ? parent / (stem.string() + " QUANT DATA.csv") : fs::absolute(args.quant_output);
            fs::path meshes = args.meshes_output.empty()
                ? parent / (stem.string() + " SOLIDS.pkl") : fs::absolute(args.meshes_output);

            run_quantification(wireframe_pkl, tracers, quant, meshes, args.skip_slice);

            std::cout << "Tracers: " << tracers << "\n";
            std::cout << "Quant CSV: " << quant << "\n";
            std::cout << "Meshes: " << meshes << "\n";
        } else {
            std::cout << "Skipping quantification. Use --run-quant to enable.\n";
        }

        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }
}
