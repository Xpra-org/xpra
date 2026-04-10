-- xpra_dissector.lua
-- Wireshark / tshark Lua dissector for the Xpra remote display protocol.
--
-- Installation:
--   Linux / macOS : ~/.config/wireshark/plugins/xpra_dissector.lua
--   Windows       : %APPDATA%\Wireshark\plugins\xpra_dissector.lua
--
-- After installing: Analyze → Reload Lua Plugins  (Ctrl+Shift+L)
--
-- The dissector registers on TCP port 14500 (xpra default) and also
-- installs a heuristic detector so it picks up traffic on any port.
-- Use Decode As → Xpra to force it on a different port.
--
-- LZ4 decompression is implemented in pure Lua (no external tools needed).
-- Brotli-compressed packets are shown as raw bytes only.
-- Encrypted packets (FLAGS_CIPHER) are shown as raw bytes only.

local bit = require("bit")
local band, bor, rshift = bit.band, bit.bor, bit.rshift

-- ═══════════════════════════════════════════════════════════════════════════
-- Protocol object and field declarations
-- ═══════════════════════════════════════════════════════════════════════════

local p_xpra = Proto("xpra", "Xpra Remote Display Protocol")

local pf = {
    -- header
    magic        = ProtoField.string ("xpra.magic",            "Magic"),
    flags        = ProtoField.uint8  ("xpra.flags",            "Protocol Flags",    base.HEX),
    fl_rencode   = ProtoField.bool   ("xpra.flags.rencode",    "Rencode",    8, nil, 0x01),
    fl_cipher    = ProtoField.bool   ("xpra.flags.cipher",     "Cipher",     8, nil, 0x02),
    fl_yaml      = ProtoField.bool   ("xpra.flags.yaml",       "YAML",       8, nil, 0x04),
    fl_flush     = ProtoField.bool   ("xpra.flags.flush",      "Flush",      8, nil, 0x08),
    fl_rencplus  = ProtoField.bool   ("xpra.flags.rencodeplus","Rencodeplus",8, nil, 0x10),
    level        = ProtoField.uint8  ("xpra.level",            "Level",      base.HEX),
    lv_lz4       = ProtoField.bool   ("xpra.level.lz4",        "LZ4",        8, nil, 0x10),
    lv_brotli    = ProtoField.bool   ("xpra.level.brotli",     "Brotli",     8, nil, 0x40),
    pkt_index    = ProtoField.uint8  ("xpra.index",            "Packet Index",      base.DEC),
    data_size    = ProtoField.uint32 ("xpra.data_size",        "Payload Size",      base.DEC),
    encoding     = ProtoField.string ("xpra.encoding",         "Encoding"),
    compression  = ProtoField.string ("xpra.compression",      "Compression"),
    -- payload
    payload_raw  = ProtoField.bytes  ("xpra.payload",          "Payload"),
    decoded      = ProtoField.string ("xpra.decoded",          "Decoded"),
    pkt_type     = ProtoField.string ("xpra.packet_type",      "Packet Type"),
}
p_xpra.fields = pf

-- ═══════════════════════════════════════════════════════════════════════════
-- Constants  (xpra/net/protocol/header.py)
-- ═══════════════════════════════════════════════════════════════════════════

local FLAGS_RENCODE      = 0x01
local FLAGS_CIPHER       = 0x02
local FLAGS_YAML         = 0x04
-- local FLAGS_FLUSH     = 0x08   -- not needed in dissector logic
local FLAGS_RENCODEPLUS  = 0x10

local LZ4_FLAG    = 0x10
local BROTLI_FLAG = 0x40

local HEADER_SIZE = 8

-- ═══════════════════════════════════════════════════════════════════════════
-- LZ4 block decompressor (pure Lua)
--
-- Payload layout (xpra/net/lz4/lz4.pyx):
--   bytes 0-3  : uncompressed size, little-endian uint32  (@I)
--   bytes 4..  : raw LZ4 block (no frame header)
-- ═══════════════════════════════════════════════════════════════════════════

local function lz4_decompress(data)
    if #data < 4 then return nil, "payload too short" end

    local b0, b1, b2, b3 = data:byte(1, 4)
    local uncompressed_size = b0 + b1*256 + b2*65536 + b3*16777216

    local out   = {}   -- output bytes as numbers
    local out_n = 0
    local pos   = 5    -- skip the 4-byte size header
    local src_n = #data

    while pos <= src_n do
        local token = data:byte(pos); pos = pos + 1

        -- literal length (high nibble of token)
        local lit_len = rshift(token, 4)
        if lit_len == 15 then
            repeat
                local x = data:byte(pos); pos = pos + 1
                lit_len = lit_len + x
            until x ~= 255
        end

        -- copy literals
        for i = pos, pos + lit_len - 1 do
            out_n = out_n + 1
            out[out_n] = data:byte(i)
        end
        pos = pos + lit_len

        if pos > src_n then break end   -- last sequence has no match

        -- match offset (little-endian 16-bit)
        local match_offset = data:byte(pos) + data:byte(pos + 1) * 256
        pos = pos + 2
        if match_offset == 0 then return nil, "invalid offset 0" end

        -- match length (low nibble + 4, then optional extra bytes)
        local match_len = band(token, 0x0F) + 4
        if band(token, 0x0F) == 15 then
            repeat
                local x = data:byte(pos); pos = pos + 1
                match_len = match_len + x
            until x ~= 255
        end

        -- copy match — single-step handles overlapping runs correctly
        local match_start = out_n - match_offset + 1
        for i = 0, match_len - 1 do
            out_n = out_n + 1
            out[out_n] = out[match_start + i]
        end
    end

    if out_n ~= uncompressed_size then
        -- non-fatal: stream may have been truncated; return what we have
    end

    local chars = {}
    for i = 1, out_n do chars[i] = string.char(out[i]) end
    return table.concat(chars)
end

-- ═══════════════════════════════════════════════════════════════════════════
-- rencodeplus decoder  (xpra/net/rencodeplus/rencodeplus.pyx)
--
-- Returns (display_string, new_pos).
-- Strings and containers are truncated for display; the full bytes are
-- always available in the raw payload field.
-- ═══════════════════════════════════════════════════════════════════════════

local MAX_STR   = 80    -- characters shown inline for strings
local MAX_ITEMS = 64    -- max list / dict entries before "…"

local rp_decode  -- forward declaration for mutual recursion

rp_decode = function(s, pos)
    local b = s:byte(pos)

    -- positive fixed int  0x00–0x2B (0–43)
    if b < 44 then return tostring(b), pos + 1 end

    -- CHR_FLOAT64 = 44
    if b == 44 then return "<f64>", pos + 9 end

    -- 48–57: ASCII digit → variable-length encoding
    --   "N:..."  strings (str type, UTF-8)
    --   "N/..."  bytes   (bytes type, shown as hex)
    if b >= 48 and b <= 57 then
        local x = pos
        while true do
            local c = s:byte(x)
            if c == 58 or c == 47 then break end   -- ':' or '/'
            x = x + 1
        end
        local sep    = s:byte(x)         -- 58=':' or 47='/'
        local n      = tonumber(s:sub(pos, x - 1))
        local dstart = x + 1
        if sep == 47 then  -- bytes
            local hex = s:sub(dstart, dstart + math.min(n, 16) - 1)
                          :gsub(".", function(c)
                              return string.format("%02x", c:byte()) end)
            return string.format("bytes[%d]:%s%s", n, hex,
                                 n > 16 and "…" or ""), dstart + n
        else               -- str
            local txt = s:sub(dstart, dstart + math.min(n, MAX_STR) - 1)
            return '"' .. txt .. (n > MAX_STR and "…" or "") .. '"', dstart + n
        end
    end

    -- CHR_LIST = 59  (variable length, terminated by CHR_TERM=127)
    if b == 59 then
        local items, n = {}, 0
        pos = pos + 1
        while s:byte(pos) ~= 127 do
            n = n + 1
            local v
            v, pos = rp_decode(s, pos)
            if n <= MAX_ITEMS then
                table.insert(items, v)
            elseif n == MAX_ITEMS + 1 then
                table.insert(items, "…")
            end
        end
        return "[" .. table.concat(items, ", ") .. "]", pos + 1
    end

    -- CHR_DICT = 60  (variable length, terminated by CHR_TERM=127)
    if b == 60 then
        local items, n = {}, 0
        pos = pos + 1
        while s:byte(pos) ~= 127 do
            n = n + 1
            local k, v
            k, pos = rp_decode(s, pos)
            v, pos = rp_decode(s, pos)
            if n <= MAX_ITEMS then
                table.insert(items, k .. ": " .. v)
            elseif n == MAX_ITEMS + 1 then
                table.insert(items, "…")
            end
        end
        return "{" .. table.concat(items, ", ") .. "}", pos + 1
    end

    -- CHR_INT = 61  (big integer as ASCII digits, terminated by CHR_TERM=127)
    if b == 61 then
        pos = pos + 1
        local st = pos
        while s:byte(pos) ~= 127 do pos = pos + 1 end
        return s:sub(st, pos - 1), pos + 1
    end

    -- CHR_INT1 = 62  (signed 8-bit)
    if b == 62 then
        local v = s:byte(pos + 1)
        if v >= 128 then v = v - 256 end
        return tostring(v), pos + 2
    end

    -- CHR_INT2 = 63  (signed 16-bit big-endian)
    if b == 63 then
        local hi, lo = s:byte(pos + 1), s:byte(pos + 2)
        local v = hi * 256 + lo
        if v >= 32768 then v = v - 65536 end
        return tostring(v), pos + 3
    end

    -- CHR_INT4 = 64  (signed 32-bit big-endian)
    if b == 64 then
        local b1, b2, b3, b4 = s:byte(pos+1), s:byte(pos+2), s:byte(pos+3), s:byte(pos+4)
        local v = ((b1 * 256 + b2) * 256 + b3) * 256 + b4
        if v >= 2147483648 then v = v - 4294967296 end
        return tostring(v), pos + 5
    end

    -- CHR_INT8 = 65  (signed 64-bit big-endian — shown as hex; Lua has no int64)
    if b == 65 then
        local hex = string.format("%02x%02x%02x%02x%02x%02x%02x%02x",
            s:byte(pos+1), s:byte(pos+2), s:byte(pos+3), s:byte(pos+4),
            s:byte(pos+5), s:byte(pos+6), s:byte(pos+7), s:byte(pos+8))
        return "0x" .. hex, pos + 9
    end

    -- CHR_FLOAT32 = 66
    if b == 66 then return "<f32>", pos + 5 end

    -- CHR_TRUE = 67 / CHR_FALSE = 68 / CHR_NONE = 69
    if b == 67 then return "True",  pos + 1 end
    if b == 68 then return "False", pos + 1 end
    if b == 69 then return "None",  pos + 1 end

    -- fixed negative int  70–101  →  -1 .. -32
    if b >= 70 and b <= 101 then
        return tostring(-(b - 70 + 1)), pos + 1
    end

    -- fixed dict  102–126  (length embedded in typecode)
    if b >= 102 and b <= 126 then
        local count = b - 102
        local items = {}
        pos = pos + 1
        for _ = 1, count do
            local k, v
            k, pos = rp_decode(s, pos)
            v, pos = rp_decode(s, pos)
            table.insert(items, k .. ": " .. v)
        end
        return "{" .. table.concat(items, ", ") .. "}", pos
    end

    -- CHR_TERM = 127  (should never be the first byte of a value)
    if b == 127 then error("unexpected CHR_TERM at pos " .. pos) end

    -- fixed string  128–191  (length = typecode - 128)
    if b >= 128 and b <= 191 then
        local L   = b - 128
        local txt = s:sub(pos + 1, pos + math.min(L, MAX_STR))
        return '"' .. txt .. (L > MAX_STR and "…" or "") .. '"', pos + 1 + L
    end

    -- fixed list  192–255  (length = typecode - 192)
    if b >= 192 then
        local count = b - 192
        local items = {}
        pos = pos + 1
        for _ = 1, count do
            local v
            v, pos = rp_decode(s, pos)
            table.insert(items, v)
        end
        return "[" .. table.concat(items, ", ") .. "]", pos
    end

    return string.format("<0x%02x>", b), pos + 1
end

-- ═══════════════════════════════════════════════════════════════════════════
-- Small helpers
-- ═══════════════════════════════════════════════════════════════════════════

local function encoding_name(flags)
    if band(flags, FLAGS_RENCODEPLUS) ~= 0 then return "rencodeplus" end
    if band(flags, FLAGS_RENCODE)     ~= 0 then return "rencode"     end
    if band(flags, FLAGS_YAML)        ~= 0 then return "yaml"        end
    if band(flags, FLAGS_CIPHER)      ~= 0 then return "cipher"      end
    return "bencode"
end

local function compression_name(level)
    if band(level, LZ4_FLAG)    ~= 0 then
        return string.format("lz4(%d)", band(level, 0x0F))
    end
    if band(level, BROTLI_FLAG) ~= 0 then
        return string.format("brotli(%d)", band(level, 0x0F))
    end
    if level == 0 then return "none" end
    return string.format("zlib(%d)", level)
end

-- ═══════════════════════════════════════════════════════════════════════════
-- Main dissector
-- ═══════════════════════════════════════════════════════════════════════════

function p_xpra.dissector(tvb, pinfo, tree)
    local tvb_len = tvb:len()
    local offset  = 0

    pinfo.cols.protocol:set("Xpra")

    while offset < tvb_len do

        -- ── wait for the 8-byte header ───────────────────────────────
        if tvb_len - offset < HEADER_SIZE then
            pinfo.desegment_offset = offset
            pinfo.desegment_len    = DESEGMENT_ONE_MORE_SEGMENT
            return
        end

        if tvb(offset, 1):uint() ~= 0x50 then return 0 end  -- not 'P'

        local flags     = tvb(offset + 1, 1):uint()
        local level     = tvb(offset + 2, 1):uint()
        local pkt_idx   = tvb(offset + 3, 1):uint()
        local data_size = tvb(offset + 4, 4):uint()
        local pdu_len   = HEADER_SIZE + data_size

        -- ── wait for the complete PDU ────────────────────────────────
        if tvb_len - offset < pdu_len then
            pinfo.desegment_offset = offset
            pinfo.desegment_len    = pdu_len - (tvb_len - offset)
            return
        end

        -- ── build subtree ────────────────────────────────────────────
        local enc   = encoding_name(flags)
        local comp  = compression_name(level)
        local label = string.format("[idx=%d]  %s  %s  %d bytes",
                                    pkt_idx, enc, comp, data_size)
        local pkt_tree = tree:add(p_xpra, tvb(offset, pdu_len), label)

        -- header fields
        local hdr = pkt_tree:add(tvb(offset, HEADER_SIZE), "Header")
        hdr:add(pf.magic,   tvb(offset, 1))

        local fl_tree = hdr:add(pf.flags, tvb(offset + 1, 1))
        fl_tree:add(pf.fl_rencplus, tvb(offset + 1, 1))
        fl_tree:add(pf.fl_flush,    tvb(offset + 1, 1))
        fl_tree:add(pf.fl_yaml,     tvb(offset + 1, 1))
        fl_tree:add(pf.fl_cipher,   tvb(offset + 1, 1))
        fl_tree:add(pf.fl_rencode,  tvb(offset + 1, 1))
        hdr:add(pf.encoding,        tvb(offset + 1, 1), enc)

        local lv_tree = hdr:add(pf.level, tvb(offset + 2, 1))
        lv_tree:add(pf.lv_brotli, tvb(offset + 2, 1))
        lv_tree:add(pf.lv_lz4,   tvb(offset + 2, 1))
        hdr:add(pf.compression,   tvb(offset + 2, 1), comp)

        hdr:add(pf.pkt_index, tvb(offset + 3, 1))
        hdr:add(pf.data_size, tvb(offset + 4, 4))

        -- raw payload
        local payload_range = tvb(offset + HEADER_SIZE, data_size)
        pkt_tree:add(pf.payload_raw, payload_range)

        -- ── decode index-0 packets ───────────────────────────────────
        -- index > 0 are raw binary continuation chunks (e.g. pixel data)
        -- for a large multi-part logical packet; show them as-is.
        if pkt_idx > 0 then
            pkt_tree:add(string.format(
                "[Chunk #%d: raw continuation payload for current logical packet]",
                pkt_idx))

        elseif band(flags, FLAGS_CIPHER) ~= 0 then
            pkt_tree:add("[Encrypted payload — cannot decode without the key]")

        elseif data_size > 0 then
            local raw = payload_range:raw()

            -- decompress lz4
            if band(level, LZ4_FLAG) ~= 0 then
                local ok, result = pcall(lz4_decompress, raw)
                if ok and result then
                    pkt_tree:add(string.format(
                        "lz4 decompressed: %d → %d bytes", data_size, #result))
                    raw = result
                else
                    pkt_tree:add("[lz4 decompression failed: " .. tostring(result) .. "]")
                    raw = nil
                end
            elseif band(level, BROTLI_FLAG) ~= 0 then
                pkt_tree:add("[brotli: not implemented — raw bytes only]")
                raw = nil
            end

            -- decode rencodeplus
            if raw and band(flags, FLAGS_RENCODEPLUS) ~= 0 then
                local ok, result = pcall(rp_decode, raw, 1)
                if ok then
                    pkt_tree:add(pf.decoded,   payload_range, result)
                    -- packet type is the first element of the outer list
                    local ptype = result:match('^%["([^"]+)"')
                              or  result:match('^%[([%w_%-]+)')
                    if ptype then
                        pkt_tree:add(pf.pkt_type, payload_range, ptype)
                        pinfo.cols.info:append("  " .. ptype)
                    end
                else
                    pkt_tree:add("[rencodeplus decode error: " .. tostring(result) .. "]")
                end
            end
        end

        offset = offset + pdu_len
    end
end

-- ═══════════════════════════════════════════════════════════════════════════
-- Registration
-- ═══════════════════════════════════════════════════════════════════════════

-- Fixed port (xpra default: 14500; also common: 14501, 14502 …)
local tcp_table = DissectorTable.get("tcp.port")
tcp_table:add(14500, p_xpra)

-- Heuristic: auto-detect on any TCP port.
-- Checks: magic byte 'P', a known encoding flag, index 0, sane payload size.
p_xpra:register_heuristic("tcp", function(tvb, pinfo, tree)
    if tvb:len() < HEADER_SIZE then return false end
    if tvb(0, 1):uint() ~= 0x50 then return false end

    local flags = tvb(1, 1):uint()
    local idx   = tvb(3, 1):uint()
    local sz    = tvb(4, 4):uint()

    if idx ~= 0 then return false end
    -- at least one encoding flag must be set (bencode=0 is too ambiguous)
    local enc_flags = band(flags, bor(bor(FLAGS_RENCODE, FLAGS_YAML), FLAGS_RENCODEPLUS))
    if enc_flags == 0 then return false end
    if sz == 0 or sz > 0x4000000 then return false end  -- 0 < size < 64 MB

    p_xpra.dissector(tvb, pinfo, tree)
    return true
end)
