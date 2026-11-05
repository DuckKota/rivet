#!/usr/bin/env bash
#
# success-screen.sh — a pure-Bash success screen with confetti or fireworks.
#
# Source this file and call show_success_screen for structured content:
#
#   source ./success-screen.sh
#   show_success_screen \
#     --title "Setup complete" \
#     --subtitle "Your development environment is ready." \
#     --command "my-tool start" \
#     --step "my-tool help"
#
#   show_success_screen --effect fireworks --title "Setup complete"
#
# Or call show_success_block with any lines, including pre-colored text or art:
#
#   show_success_block --check \
#     '  /\_/\  ' \
#     ' ( o.o ) ' \
#     '  > ^ <  '
#
# Running this file directly shows a demo. It uses only Bash built-ins,
# tput for capability/size checks, and sleep for frame timing. The animation
# clears the viewport once (like clear -x) and parks the cursor at the bottom.

CONFETTI_FPS=${CONFETTI_FPS:-24}
CONFETTI_PARTICLES=${CONFETTI_PARTICLES:-42}
CONFETTI_DURATION=${CONFETTI_DURATION:-1800}   # total animation budget, ms
CONFETTI_GRAVITY=${CONFETTI_GRAVITY:-7}        # fixed-point units/frame^2 at 24 FPS
CONFETTI_UNICODE=${CONFETTI_UNICODE:-auto}     # auto | 1 | 0
CONFETTI_COLOR=${CONFETTI_COLOR:-auto}         # auto | 1 | 0
CONFETTI_COLORS=${CONFETTI_COLORS:-"96 95 93 94 39"} # ANSI 16-colour SGR codes

FIREWORKS_FPS=${FIREWORKS_FPS:-24}
FIREWORKS_SHELLS=${FIREWORKS_SHELLS:-4}          # rockets launched per run
FIREWORKS_SPARKS=${FIREWORKS_SPARKS:-20}         # sparks per explosion
FIREWORKS_DURATION=${FIREWORKS_DURATION:-2800}   # total animation budget, ms
FIREWORKS_GRAVITY=${FIREWORKS_GRAVITY:-6}        # fixed-point units/frame^2 at 24 FPS
FIREWORKS_UNICODE=${FIREWORKS_UNICODE:-auto}     # auto | 1 | 0
FIREWORKS_COLOR=${FIREWORKS_COLOR:-auto}         # auto | 1 | 0
FIREWORKS_COLORS=${FIREWORKS_COLORS:-"91 93 96 95 94 92"} # ANSI 16-colour SGR codes

_ss_esc=$'\e'
_ss_reset=""
_ss_stride=0
_ss_frame_buf=""
_ss_frame=0
_ss_animating=0
_ss_cursor_hidden=0
_ss_traps_set=0
_ss_old_exit=""
_ss_old_int=""
_ss_old_term=""
_ss_old_hup=""

_ss_raw_lines=()
_ss_raw_widths=()
_ss_raw_maxw=0
_ss_raw_top=0
_ss_raw_block_top=0
_ss_raw_block_col=1
_ss_raw_check_row=0
_ss_raw_check_col=0
_ss_raw_has_check=0
_ss_raw_center_lines=0
_ss_raw_layout_ok=0
_ss_raw_animate_ok=0

# 16 directions, flattened vertically because terminal cells are ~2:1.
_ss_dir_vx=(100 92 71 38 0 -38 -71 -92 -100 -92 -71 -38 0 38 71 92)
_ss_dir_vy=(0 19 35 46 50 46 35 19 0 -19 -35 -46 -50 -46 -35 -19)
_ss_wobble=(-4 -2 0 2 4 2 0 -2)

_ss_usage() {
  printf '%s\n' \
    'Usage: show_success_screen [options]' \
    '  --title TEXT       success headline (default: Success)' \
    '  --subtitle TEXT    supporting sentence' \
    '  --command TEXT     primary next command' \
    '  --step TEXT        additional next step (repeatable)' \
    '  --steps A|B|C      additional next steps, pipe-separated' \
    '  --info TEXT        optional extra information' \
    '  --effect MODE      confetti or fireworks (default: confetti)' \
    '  --static           render the static screen only' \
    '' \
    'Positional: title [subtitle [command [step ...]]]' \
    '' \
    'Config: CONFETTI_* for confetti; FIREWORKS_* for fireworks.'
}

_ss_confetti_usage() {
  printf '%s\n' \
    'Usage: show_success_block [options] "line" "line" ...' \
    '  --effect MODE      confetti or fireworks (default: confetti)' \
    '  --check            show a standalone checkmark before the block' \
    '  --center-lines     center each line instead of centering the block' \
    '  --static           render the block without animation' \
    '  --                 end options; use for lines beginning with -' \
    '' \
    'Lines are rendered as-is. ANSI SGR colour is preserved, and visible' \
    'width is measured with escapes ignored. The block is centered as one' \
    'unit by default, which keeps block art aligned.' \
    '' \
    'Config: CONFETTI_* for confetti; FIREWORKS_* for fireworks.'
}

_ss_parse_args() {
  _ss_title=""
  _ss_subtitle=""
  _ss_command=""
  _ss_info=""
  _ss_steps=()
  _ss_force_static=0

  if (( $# > 0 )) && [[ $1 != -* ]]; then
    _ss_title=$1
    shift
    if (( $# > 0 )); then _ss_subtitle=$1; shift; fi
    if (( $# > 0 )); then _ss_command=$1; shift; fi
    while (( $# > 0 )); do _ss_steps+=("$1"); shift; done
    return 0
  fi

  while (( $# > 0 )); do
    case $1 in
      --title|--subtitle|--command|--info|--step|--steps)
        if (( $# < 2 )); then
          printf 'show_success_screen: %s needs a value\n' "$1" >&2
          return 1
        fi
        case $1 in
          --title) _ss_title=$2 ;;
          --subtitle) _ss_subtitle=$2 ;;
          --command) _ss_command=$2 ;;
          --info) _ss_info=$2 ;;
          --step) _ss_steps+=("$2") ;;
          --steps)
            local _ss_tmp=() _ss_part
            IFS='|' read -r -a _ss_tmp <<< "$2" || true
            if (( ${#_ss_tmp[@]} > 0 )); then
              for _ss_part in "${_ss_tmp[@]}"; do
                [[ -n $_ss_part ]] && _ss_steps+=("$_ss_part")
              done
            fi
            ;;
        esac
        shift 2
        ;;
      --effect)
        if (( $# < 2 )); then
          printf 'show_success_screen: --effect needs a value\n' >&2
          return 1
        fi
        _ss_effect=$2
        shift 2
        ;;
      --static) _ss_force_static=1; shift ;;
      -h|--help) _ss_usage; return 2 ;;
      *)
        printf 'show_success_screen: unknown option: %s\n' "$1" >&2
        return 1
        ;;
    esac
  done
  return 0
}

_ss_config() {
  local v
  _ss_effect=${_ss_effect:-confetti}
  case $_ss_effect in
    confetti|fireworks) ;;
    *) _ss_effect=confetti ;;
  esac

  if [[ $_ss_effect == fireworks ]]; then
    v=${FIREWORKS_FPS:-24}
    if ! [[ $v =~ ^[0-9]+$ ]]; then v=24; fi
    if (( v < 10 )); then v=10; fi
    if (( v > 60 )); then v=60; fi
    _ss_fps=$v

    v=${FIREWORKS_SHELLS:-4}
    if ! [[ $v =~ ^[0-9]+$ ]]; then v=4; fi
    if (( v < 2 )); then v=2; fi
    if (( v > 6 )); then v=6; fi
    _ss_shells=$v

    v=${FIREWORKS_SPARKS:-20}
    if ! [[ $v =~ ^[0-9]+$ ]]; then v=20; fi
    if (( v < 8 )); then v=8; fi
    if (( v > 28 )); then v=28; fi
    _ss_sparks=$v

    v=${FIREWORKS_DURATION:-2800}
    if ! [[ $v =~ ^[0-9]+$ ]]; then v=2800; fi
    if (( v < 1800 )); then v=1800; fi
    if (( v > 8000 )); then v=8000; fi
    _ss_duration=$v

    v=${FIREWORKS_GRAVITY:-6}
    if ! [[ $v =~ ^[0-9]+$ ]]; then v=6; fi
    if (( v < 2 )); then v=2; fi
    if (( v > 14 )); then v=14; fi
    _ss_gravity=$v

    _ss_colors=${FIREWORKS_COLORS:-"91 93 96 95 94 92"}
    return 0
  fi

  v=${CONFETTI_FPS:-24}
  if ! [[ $v =~ ^[0-9]+$ ]]; then v=24; fi
  if (( v < 10 )); then v=10; fi
  if (( v > 60 )); then v=60; fi
  _ss_fps=$v

  v=${CONFETTI_PARTICLES:-42}
  if ! [[ $v =~ ^[0-9]+$ ]]; then v=42; fi
  if (( v < 8 )); then v=8; fi
  if (( v > 100 )); then v=100; fi
  _ss_particles=$v

  v=${CONFETTI_DURATION:-1800}
  if ! [[ $v =~ ^[0-9]+$ ]]; then v=1800; fi
  if (( v < 1200 )); then v=1200; fi
  if (( v > 6000 )); then v=6000; fi
  _ss_duration=$v

  v=${CONFETTI_GRAVITY:-7}
  if ! [[ $v =~ ^[0-9]+$ ]]; then v=7; fi
  if (( v < 2 )); then v=2; fi
  if (( v > 20 )); then v=20; fi
  _ss_gravity=$v

  _ss_colors=${CONFETTI_COLORS:-"96 95 93 94 39"}
  return 0
}

_ss_detect_size() {
  local c="" l=""
  if (( _ss_tty )); then
    if command -v tput >/dev/null 2>&1; then
      c=$(tput cols) 2>/dev/null || c=""
      l=$(tput lines) 2>/dev/null || l=""
    fi
  fi
  if ! [[ $c =~ ^[0-9]+$ ]] || (( c <= 0 )); then c=${COLUMNS:-80}; fi
  if ! [[ $l =~ ^[0-9]+$ ]] || (( l <= 0 )); then l=${LINES:-24}; fi
  if ! [[ $c =~ ^[0-9]+$ ]] || (( c <= 0 )); then c=80; fi
  if ! [[ $l =~ ^[0-9]+$ ]] || (( l <= 0 )); then l=24; fi
  _ss_cols=$c
  _ss_lines=$l
  _ss_stride=$((_ss_cols + 2))
}

_ss_detect_unicode() {
  local mode cm="" loc=""
  if [[ $_ss_effect == fireworks ]]; then
    mode=${FIREWORKS_UNICODE:-auto}
  else
    mode=${CONFETTI_UNICODE:-auto}
  fi
  case $mode in
    0|false|no|off) _ss_unicode=0; return 0 ;;
    1|true|yes|on) _ss_unicode=1; return 0 ;;
  esac
  if command -v locale >/dev/null 2>&1; then
    cm=$(locale charmap) 2>/dev/null || cm=""
  fi
  case $cm in
    *UTF-8*|*utf8*|*UTF8*) _ss_unicode=1; return 0 ;;
  esac
  loc=${LC_ALL:-${LC_CTYPE:-${LANG:-}}}
  case $loc in
    *UTF-8*|*utf8*|*UTF8*) _ss_unicode=1 ;;
    *) _ss_unicode=0 ;;
  esac
  return 0
}

_ss_detect_color() {
  _ss_color=0
  _ss_color_count=0
  (( _ss_tty )) || return 0
  if [[ ${NO_COLOR+x} ]]; then return 0; fi
  if [[ ${CLICOLOR:-} == 0 ]]; then return 0; fi
  if [[ $_ss_effect == fireworks ]]; then
    case ${FIREWORKS_COLOR:-auto} in
      0|false|no|off) return 0 ;;
      1|true|yes|on) _ss_color=1; _ss_color_count=16; return 0 ;;
    esac
  else
    case ${CONFETTI_COLOR:-auto} in
      0|false|no|off) return 0 ;;
      1|true|yes|on) _ss_color=1; _ss_color_count=16; return 0 ;;
    esac
  fi
  [[ ${TERM:-dumb} == dumb ]] && return 0
  if command -v tput >/dev/null 2>&1; then
    local n
    n=$(tput colors) 2>/dev/null || n=0
    if [[ $n =~ ^[0-9]+$ ]] && (( n >= 8 )); then
      _ss_color=1
      _ss_color_count=$n
    fi
  fi
  return 0
}

_ss_detect_terminal() {
  _ss_can_animate=0
  _ss_civis=""
  _ss_cnorm=""
  _ss_cup=""
  (( _ss_tty )) || return 0
  [[ ${TERM:-dumb} == dumb ]] && return 0
  command -v tput >/dev/null 2>&1 || return 0
  _ss_civis=$(tput civis) 2>/dev/null || _ss_civis=""
  _ss_cnorm=$(tput cnorm) 2>/dev/null || _ss_cnorm=""
  _ss_cup=$(tput cup 0 0) 2>/dev/null || _ss_cup=""
  if [[ -n $_ss_civis && -n $_ss_cnorm && -n $_ss_cup ]]; then
    _ss_can_animate=1
  fi
  return 0
}

_ss_build_styles() {
  if (( _ss_color )); then
    _ss_reset=$'\e[0m'
    _ss_c_bold=$'\e[1m'
    _ss_c_dim=$'\e[2m'
    _ss_c_green=$'\e[32m'
    _ss_c_cyan=$'\e[36m'
    _ss_c_green_bold="${_ss_c_bold}${_ss_c_green}"
    _ss_c_title="$_ss_c_bold"
    _ss_c_command="${_ss_c_bold}${_ss_c_cyan}"
    if (( _ss_color_count >= 16 )); then
      _ss_c_command_pulse="${_ss_c_bold}"$'\e[96m'
    else
      _ss_c_command_pulse="$_ss_c_command"
    fi
    _ss_c_text=""
    _ss_c_info="$_ss_c_dim"
    _ss_c_heading="$_ss_c_dim"
    _ss_c_prefix="$_ss_c_dim"
    if (( _ss_color_count >= 16 )); then
      _ss_c_rocket="${_ss_c_bold}"$'\e[93m'
    else
      _ss_c_rocket="$_ss_c_bold"
    fi
  else
    _ss_reset=""
    _ss_c_bold=""
    _ss_c_dim=""
    _ss_c_green=""
    _ss_c_cyan=""
    _ss_c_green_bold=""
    _ss_c_title=""
    _ss_c_command=""
    _ss_c_command_pulse=""
    _ss_c_text=""
    _ss_c_info=""
    _ss_c_heading=""
    _ss_c_prefix=""
    _ss_c_rocket=""
  fi
}

_ss_build_chars() {
  if (( _ss_unicode )); then
    _ss_check="✓"
    _ss_step_prefix="›"
    _ss_ellipsis="…"
    _ss_rocket="│"
    _ss_trail_char="·"
    if [[ $_ss_effect == fireworks ]]; then
      _ss_chars=("✦" "✧" "•" "*" "+" "·" "·")
    else
      _ss_chars=("·" "·" "•" "•" "*" "*" "+" "✦" "✧")
    fi
  else
    _ss_check="+"
    _ss_step_prefix=">"
    _ss_ellipsis="..."
    _ss_rocket="|"
    _ss_trail_char="."
    if [[ $_ss_effect == fireworks ]]; then
      _ss_chars=("*" "+" "." "." "o")
    else
      _ss_chars=("." "." "*" "*" "+" "o")
    fi
  fi
}

_ss_build_palette() {
  _ss_conf_bright=()
  _ss_conf_muted=()
  if (( _ss_color )); then
    local c m
    local IFS=$' \t\n'
    for c in $_ss_colors; do
      [[ $c =~ ^[0-9]+$ ]] || continue
      if (( c >= 90 && c <= 97 )); then
        if (( _ss_color_count < 16 )); then
          c=$((c - 60))
          m=$c
        else
          m=$((c - 60))
        fi
      elif (( c >= 30 && c <= 37 )); then
        m=$c
      elif (( c == 39 )); then
        m=39
      else
        continue
      fi
      _ss_conf_bright+=("${_ss_esc}[${c}m")
      _ss_conf_muted+=("${_ss_esc}[${m}m")
    done
  fi
  if (( ${#_ss_conf_bright[@]} == 0 )); then
    _ss_conf_bright=("" "" "" "" "")
    _ss_conf_muted=("" "" "" "" "")
  fi
  _ss_palette_n=${#_ss_conf_bright[@]}
}

_ss_detect() {
  _ss_tty=0
  if [[ -t 1 ]]; then _ss_tty=1; fi
  _ss_animating=0
  _ss_cursor_hidden=0
  _ss_traps_set=0
  _ss_detect_size
  _ss_detect_unicode
  _ss_detect_color
  _ss_detect_terminal
  _ss_build_styles
  _ss_build_chars
  _ss_build_palette
  _ss_clear_screen="${_ss_esc}[2J${_ss_esc}[H"
  return 0
}

# Walk a raw line once. Modes: len (count visible), clip (escapes + visible up
# to max), plain (visible up to max, escapes dropped), strip (visible only).
_ss_scan_raw() {
  local s=$1 mode=$2 max=${3:-0}
  local out="" vis=0 i=0 n=${#s} ch next j final
  while (( i < n )); do
    ch=${s:i:1}
    if [[ $ch == $'\e' ]]; then
      j=$((i + 1))
      if (( j >= n )); then break; fi
      next=${s:j:1}
      final=""
      if [[ $next == '[' ]]; then
        j=$((j + 1))
        while (( j < n )); do
          ch=${s:j:1}
          j=$((j + 1))
          case $ch in
            [A-Za-z]) final=$ch; break ;;
          esac
        done
      elif [[ $next == ']' ]]; then
        j=$((j + 1))
        while (( j < n )); do
          ch=${s:j:1}
          if [[ $ch == $'\a' ]]; then
            j=$((j + 1))
            break
          fi
          if [[ $ch == $'\e' && ${s:j+1:1} == $'\\' ]]; then
            j=$((j + 2))
            break
          fi
          j=$((j + 1))
        done
      elif [[ $next == '(' || $next == ')' ]]; then
        j=$((j + 2))
      else
        j=$((j + 1))
      fi
      # Only SGR is safe to carry through. Cursor, erase, OSC and other
      # controls are dropped so caller content cannot move the renderer.
      if [[ $mode == clip && $final == 'm' ]]; then
        out+=${s:i:j-i}
      fi
      i=$j
      continue
    fi

    case $mode in
      len) ;;
      clip) if (( vis < max )); then out+=$ch; fi ;;
      plain) if (( vis < max )); then out+=$ch; fi ;;
      strip) out+=$ch ;;
    esac
    vis=$((vis + 1))
    i=$((i + 1))
  done
  _ss_scan_out=$out
  _ss_scan_len=$vis
  return 0
}

_ss_visible_len() {
  _ss_scan_raw "$1" len
  _ss_vis_len=$_ss_scan_len
  return 0
}

_ss_clip_raw() {
  local max=${2:-0}
  _ss_scan_raw "$1" clip "$max"
  _ss_clipped=$_ss_scan_out
  _ss_clipped_len=$_ss_scan_len
  if (( _ss_clipped_len > max )); then _ss_clipped_len=$max; fi
  return 0
}

_ss_plain_raw() {
  local max=${2:-0}
  _ss_scan_raw "$1" plain "$max"
  _ss_plain=$_ss_scan_out
  _ss_plain_len=$_ss_scan_len
  if (( _ss_plain_len > max )); then _ss_plain_len=$max; fi
  return 0
}

_ss_strip_ansi() {
  _ss_scan_raw "$1" strip
  _ss_stripped=$_ss_scan_out
  return 0
}

_ss_truncate() {
  local text=$1 max=$2 n
  if (( max < 1 )); then
    _ss_truncated=""
    return 0
  fi
  if (( ${#text} <= max )); then
    _ss_truncated=$text
    return 0
  fi
  if (( max <= 3 )); then
    _ss_truncated=${text:0:max}
    return 0
  fi
  n=$((max - ${#_ss_ellipsis}))
  _ss_truncated="${text:0:n}${_ss_ellipsis}"
}

_ss_wrap() {
  local text=$1 maxw=$2
  local -a words=()
  local word line="" n
  _ss_wrapped=()
  if (( maxw < 1 )); then maxw=1; fi
  if [[ -z $text ]]; then return 0; fi

  local IFS=$' \t\n'
  read -r -a words <<< "$text" || true
  if (( ${#words[@]} == 0 )); then return 0; fi

  for word in "${words[@]}"; do
    while (( ${#word} > maxw )); do
      if [[ -n $line ]]; then
        _ss_wrapped+=("$line")
        line=""
      fi
      _ss_wrapped+=("${word:0:maxw}")
      word=${word:maxw}
    done
    if [[ -z $word ]]; then continue; fi
    if [[ -z $line ]]; then
      line=$word
    elif (( ${#line} + 1 + ${#word} <= maxw )); then
      line+=" $word"
    else
      _ss_wrapped+=("$line")
      line=$word
    fi
  done
  if [[ -n $line ]]; then _ss_wrapped+=("$line"); fi
  return 0
}

_ss_reset_layout() {
  _ss_l_pre=()
  _ss_l_pre_style=()
  _ss_l_text=()
  _ss_l_style=()
  _ss_l_align=()
  _ss_l_stage=()
  _ss_l_col=()
  _ss_l_row=()
  _ss_wrapped=()
  _ss_check_line=-1
  _ss_check_row=0
  _ss_check_col=0
  _ss_cmd_lines=()
}

_ss_add_line() {
  _ss_l_pre+=("$1")
  _ss_l_pre_style+=("$2")
  _ss_l_text+=("$3")
  _ss_l_style+=("$4")
  _ss_l_align+=("$5")
  _ss_l_stage+=("$6")
}

_ss_build_layout() {
  local include_info=${1:-1}
  local maxw=$((_ss_cols - 4))
  local contentw i line first step_count has_next
  if (( maxw > 64 )); then maxw=64; fi
  if (( maxw < 12 )); then maxw=12; fi
  contentw=$((maxw - 3))
  if (( contentw < 8 )); then contentw=8; fi
  step_count=${#_ss_steps[@]}
  has_next=0
  if [[ -n $_ss_command ]] || (( step_count > 0 )); then has_next=1; fi

  _ss_reset_layout

  # Stage 0: standalone success beat.
  _ss_add_line "" "" "$_ss_check" "$_ss_c_green_bold" center 0
  _ss_check_line=$(( ${#_ss_l_text[@]} - 1 ))

  # Stage 1: title block.
  _ss_truncate "${_ss_title:-Success}" "$contentw"
  _ss_add_line "" "" "$_ss_truncated" "$_ss_c_title" center 1

  if [[ -n $_ss_subtitle ]]; then
    _ss_wrap "$_ss_subtitle" "$maxw"
    if (( ${#_ss_wrapped[@]} > 0 )); then
      for line in "${_ss_wrapped[@]}"; do
        _ss_add_line "" "" "$line" "$_ss_c_text" center 1
      done
    fi
  fi

  if (( include_info )) && [[ -n $_ss_info ]]; then
    _ss_wrap "$_ss_info" "$maxw"
    if (( ${#_ss_wrapped[@]} > 0 )); then
      for line in "${_ss_wrapped[@]}"; do
        _ss_add_line "" "" "$line" "$_ss_c_info" center 1
      done
    fi
  fi

  # Stage 2: next steps block.
  if (( has_next )); then
    _ss_add_line "" "" "" "" center 2
    _ss_add_line "" "" "Next steps" "$_ss_c_heading" center 2
    _ss_add_line "" "" "" "" center 2

    if [[ -n $_ss_command ]]; then
      _ss_wrap "$_ss_command" "$contentw"
      if (( ${#_ss_wrapped[@]} > 0 )); then
        first=1
        for line in "${_ss_wrapped[@]}"; do
          if (( first )); then
            _ss_add_line '$  ' "$_ss_c_prefix" "$line" "$_ss_c_command" block 2
            first=0
          else
            _ss_add_line "   " "" "$line" "$_ss_c_command" block 2
          fi
          _ss_cmd_lines+=($(( ${#_ss_l_text[@]} - 1 )))
        done
      fi
    fi

    for ((i=0; i<step_count; i++)); do
      _ss_wrap "${_ss_steps[i]}" "$contentw"
      if (( ${#_ss_wrapped[@]} > 0 )); then
        first=1
        for line in "${_ss_wrapped[@]}"; do
          if (( first )); then
            _ss_add_line "${_ss_step_prefix}  " "$_ss_c_prefix" "$line" "$_ss_c_text" block 2
            first=0
          else
            _ss_add_line "   " "" "$line" "$_ss_c_text" block 2
          fi
        done
      fi
    done
  fi
  return 0
}

_ss_compute_positions() {
  local n=${#_ss_l_text[@]}
  local i w pre_w block_w=0 block_col top
  for ((i=0; i<n; i++)); do
    if [[ ${_ss_l_align[i]} == block ]]; then
      w=$(( ${#_ss_l_pre[i]} + ${#_ss_l_text[i]} ))
      if (( w > block_w )); then block_w=$w; fi
    fi
  done
  block_col=1
  if (( block_w > 0 )); then block_col=$(( (_ss_cols - block_w) / 2 + 1 )); fi
  if (( block_col < 1 )); then block_col=1; fi
  top=$(( (_ss_lines - n) / 2 + 1 ))
  if (( top < 1 )); then top=1; fi

  for ((i=0; i<n; i++)); do
    _ss_l_row[i]=$((top + i))
    pre_w=${#_ss_l_pre[i]}
    w=$((pre_w + ${#_ss_l_text[i]}))
    if (( w == 0 )); then
      _ss_l_col[i]=0
    elif [[ ${_ss_l_align[i]} == block ]]; then
      _ss_l_col[i]=$block_col
    else
      _ss_l_col[i]=$(( (_ss_cols - w) / 2 + 1 ))
      if (( _ss_l_col[i] < 1 )); then _ss_l_col[i]=1; fi
    fi
  done

  if (( _ss_check_line >= 0 )); then
    _ss_check_row=${_ss_l_row[_ss_check_line]}
    _ss_check_col=${_ss_l_col[_ss_check_line]}
  fi

  _ss_layout_ok=0
  _ss_animate_ok=0
  if (( n > 0 && _ss_cols >= 20 && n <= _ss_lines - 1 )); then
    _ss_layout_ok=1
  fi
  if (( _ss_layout_ok && _ss_cols >= 30 && _ss_lines >= 12 && n <= _ss_lines - 2 )); then
    _ss_animate_ok=1
  fi
  return 0
}

_ss_prepare_static() {
  _ss_build_layout 1
  _ss_compute_positions
  if (( ! _ss_layout_ok )) && [[ -n $_ss_info ]]; then
    _ss_build_layout 0
    _ss_compute_positions
  fi
  return 0
}

_ss_prepare_raw() {
  local n=${#_ss_raw_lines[@]} i w total_h
  _ss_raw_widths=()
  _ss_raw_maxw=0
  for ((i=0; i<n; i++)); do
    _ss_visible_len "${_ss_raw_lines[i]}"
    w=$_ss_vis_len
    _ss_raw_widths[i]=$w
    if (( w > _ss_raw_maxw )); then _ss_raw_maxw=$w; fi
  done

  total_h=$n
  if (( _ss_raw_has_check )); then total_h=$((n + 2)); fi

  _ss_raw_layout_ok=0
  _ss_raw_animate_ok=0
  if (( n > 0 && _ss_cols >= 8 && total_h <= _ss_lines - 1 )); then
    _ss_raw_layout_ok=1
  fi

  _ss_raw_top=$(( (_ss_lines - total_h) / 2 + 1 ))
  if (( _ss_raw_top < 1 )); then _ss_raw_top=1; fi
  if (( _ss_raw_has_check )); then
    _ss_raw_check_row=$_ss_raw_top
    _ss_raw_block_top=$((_ss_raw_top + 2))
  else
    _ss_raw_check_row=0
    _ss_raw_block_top=$_ss_raw_top
  fi
  _ss_raw_check_col=$(( (_ss_cols - 1) / 2 + 1 ))
  if (( _ss_raw_check_col < 1 )); then _ss_raw_check_col=1; fi
  _ss_check_row=$_ss_raw_check_row
  _ss_check_col=$_ss_raw_check_col
  _ss_raw_block_col=$(( (_ss_cols - _ss_raw_maxw) / 2 + 1 ))
  if (( _ss_raw_block_col < 1 )); then _ss_raw_block_col=1; fi

  if (( _ss_raw_layout_ok && _ss_cols >= 20 && _ss_lines >= 8 \
        && total_h <= _ss_lines - 2 && _ss_raw_maxw <= _ss_cols - 1 )); then
    _ss_raw_animate_ok=1
  fi
  return 0
}

_ss_raw_col_for() {
  local i=$1
  if (( _ss_raw_center_lines )); then
    _ss_raw_line_col=$(( (_ss_cols - _ss_raw_widths[i]) / 2 + 1 ))
    if (( _ss_raw_line_col < 1 )); then _ss_raw_line_col=1; fi
  else
    _ss_raw_line_col=$_ss_raw_block_col
  fi
  return 0
}

_ss_print_raw_block() {
  local n=${#_ss_raw_lines[@]} i col pad maxw
  printf '\n'
  if (( _ss_raw_has_check )); then
    pad=$((_ss_raw_check_col - 1))
    if (( pad > 0 )); then printf '%*s' "$pad" ""; fi
    printf '%s%s%s\n\n' "$_ss_c_green_bold" "$_ss_check" "$_ss_reset"
  fi
  for ((i=0; i<n; i++)); do
    _ss_raw_col_for "$i"
    col=$_ss_raw_line_col
    pad=$((col - 1))
    if (( pad > 0 )); then printf '%*s' "$pad" ""; fi
    maxw=$((_ss_cols - col))
    if (( maxw < 1 )); then maxw=1; fi
    if (( _ss_color )); then
      _ss_clip_raw "${_ss_raw_lines[i]}" "$maxw"
      printf '%s%s\n' "$_ss_clipped" "$_ss_reset"
    else
      _ss_plain_raw "${_ss_raw_lines[i]}" "$maxw"
      printf '%s\n' "$_ss_plain"
    fi
  done
  return 0
}

_ss_print_raw_minimal() {
  local n=${#_ss_raw_lines[@]} i indent="  " maxw
  if (( _ss_cols < 8 )); then indent=""; fi
  maxw=$((_ss_cols - ${#indent} - 1))
  if (( maxw < 1 )); then maxw=1; fi
  printf '\n'
  if (( _ss_raw_has_check )); then
    printf '%s%s%s%s\n\n' "$indent" "$_ss_c_green_bold" "$_ss_check" "$_ss_reset"
  fi
  for ((i=0; i<n; i++)); do
    if (( _ss_color )); then
      _ss_clip_raw "${_ss_raw_lines[i]}" "$maxw"
      printf '%s%s%s\n' "$indent" "$_ss_clipped" "$_ss_reset"
    else
      _ss_plain_raw "${_ss_raw_lines[i]}" "$maxw"
      printf '%s%s\n' "$indent" "$_ss_plain"
    fi
  done
  return 0
}

_ss_log_raw() {
  local n=${#_ss_raw_lines[@]} i
  if (( _ss_raw_has_check )); then printf '%s\n' "$_ss_check"; fi
  for ((i=0; i<n; i++)); do
    _ss_strip_ansi "${_ss_raw_lines[i]}"
    printf '%s\n' "$_ss_stripped"
  done
  return 0
}

_ss_paint_raw_block() {
  local n=${#_ss_raw_lines[@]} i
  if (( _ss_raw_has_check )); then
    _ss_draw_check_pop 2
  fi
  for ((i=0; i<n; i++)); do
    _ss_raw_col_for "$i"
    _ss_put_raw $((_ss_raw_block_top + i)) "$_ss_raw_line_col" "${_ss_raw_lines[i]}"
  done
  return 0
}

_ss_print_layout() {
  local n=${#_ss_l_text[@]} i pad
  printf '\n'
  for ((i=0; i<n; i++)); do
    if [[ -z ${_ss_l_pre[i]} && -z ${_ss_l_text[i]} ]]; then
      printf '\n'
      continue
    fi
    pad=$((_ss_l_col[i] - 1))
    if (( pad > 0 )); then printf '%*s' "$pad" ""; fi
    if [[ -n ${_ss_l_pre[i]} ]]; then
      printf '%s%s%s' "${_ss_l_pre_style[i]}" "${_ss_l_pre[i]}" "$_ss_reset"
    fi
    printf '%s%s%s\n' "${_ss_l_style[i]}" "${_ss_l_text[i]}" "$_ss_reset"
  done
  return 0
}

_ss_paint_layout() {
  local n=${#_ss_l_text[@]} i
  _ss_mask=()
  for ((i=0; i<n; i++)); do
    if [[ -n ${_ss_l_pre[i]} || -n ${_ss_l_text[i]} ]]; then
      _ss_put "${_ss_l_row[i]}" "${_ss_l_col[i]}" \
        "${_ss_l_pre[i]}" "${_ss_l_pre_style[i]}" \
        "${_ss_l_text[i]}" "${_ss_l_style[i]}"
    fi
  done
  return 0
}

_ss_print_minimal() {
  local indent="  " maxw
  if (( _ss_cols < 8 )); then
    printf '\n'
    _ss_truncate "${_ss_title:-Success}" "$((_ss_cols - 1))"
    printf '%s\n' "$_ss_truncated"
    return 0
  fi
  if (( _ss_cols < 12 )); then indent=""; fi
  maxw=$((_ss_cols - ${#indent} - 1))
  if (( maxw < 1 )); then maxw=1; fi

  printf '\n'
  _ss_truncate "${_ss_title:-Success}" "$((maxw - 3))"
  printf '%s%s%s%s  %s%s%s\n' "$indent" "$_ss_c_green_bold" "$_ss_check" "$_ss_reset" "$_ss_c_title" "$_ss_truncated" "$_ss_reset"
  if [[ -n $_ss_subtitle ]]; then
    _ss_truncate "$_ss_subtitle" "$maxw"
    printf '%s%s%s%s\n' "$indent" "$_ss_c_info" "$_ss_truncated" "$_ss_reset"
  fi
  if [[ -n $_ss_command ]]; then
    _ss_truncate "$_ss_command" "$((maxw - 2))"
    printf '%s%s$ %s%s\n' "$indent" "$_ss_c_command" "$_ss_truncated" "$_ss_reset"
  fi
  return 0
}

_ss_log() {
  local mark="[ok]" title=${_ss_title:-Success} i
  if (( _ss_unicode )); then mark="✓"; fi
  printf '%s %s\n' "$mark" "$title"
  if [[ -n $_ss_subtitle ]]; then printf '  %s\n' "$_ss_subtitle"; fi
  if [[ -n $_ss_info ]]; then printf '  %s\n' "$_ss_info"; fi
  if [[ -n $_ss_command ]]; then printf '  Next: %s\n' "$_ss_command"; fi
  for ((i=0; i<${#_ss_steps[@]}; i++)); do
    printf '  - %s\n' "${_ss_steps[i]}"
  done
  return 0
}

_ss_init_particles() {
  local i idx speed vx vy life g count ox oy origin_key drag gbase
  count=$_ss_particles
  if (( _ss_cols < 60 || _ss_lines < 18 )); then count=$((count * 3 / 4)); fi
  if (( _ss_cols < 45 || _ss_lines < 15 )); then count=$((count / 2)); fi
  if (( _ss_cols > 120 )); then count=$((count * 5 / 4)); fi
  if (( count < 8 )); then count=8; fi
  if (( count > 90 )); then count=90; fi
  _ss_particle_count=$count

  ox=$((_ss_cols / 2)); if (( ox < 1 )); then ox=1; fi
  oy=$((_ss_lines / 2)); if (( oy < 1 )); then oy=1; fi
  _ss_origin_x=$ox
  _ss_origin_y=$oy
  origin_key=$((oy * _ss_stride + ox))

  _ss_p_x=(); _ss_p_y=(); _ss_p_vx=(); _ss_p_vy=(); _ss_p_g=()
  _ss_p_age=(); _ss_p_life=(); _ss_p_char=(); _ss_p_color=()
  _ss_p_wob=(); _ss_p_alive=()
  _ss_occ=()
  _ss_mask=()
  _ss_max_life=0

  drag=$((100 - 72 / _ss_fps)); if (( drag < 90 )); then drag=90; fi
  _ss_drag=$drag
  gbase=$((_ss_gravity * 24 * 24 / (_ss_fps * _ss_fps)))
  if (( gbase < 1 )); then gbase=1; fi

  for ((i=0; i<count; i++)); do
    idx=$(( (i * 16 / count + RANDOM % 2) % 16 ))
    speed=$(( 90 + RANDOM % 81 ))
    vx=$(( _ss_dir_vx[idx] * speed / 100 ))
    vy=$(( _ss_dir_vy[idx] * speed / 100 ))
    vx=$(( vx * 24 / _ss_fps ))
    vy=$(( vy * 24 / _ss_fps ))
    vy=$(( vy - 8 ))
    life=$(( (22 + RANDOM % 15) * _ss_fps / 24 ))
    if (( life < 8 )); then life=8; fi
    g=$(( gbase + RANDOM % 3 - 1 ))
    if (( g < 1 )); then g=1; fi

    _ss_p_x[i]=$((ox * 100))
    _ss_p_y[i]=$((oy * 100))
    _ss_p_vx[i]=$vx
    _ss_p_vy[i]=$vy
    _ss_p_g[i]=$g
    _ss_p_age[i]=0
    _ss_p_life[i]=$life
    _ss_p_char[i]=${_ss_chars[RANDOM % ${#_ss_chars[@]}]}
    _ss_p_color[i]=$(( RANDOM % _ss_palette_n ))
    _ss_p_wob[i]=$(( RANDOM % 8 ))
    _ss_p_alive[i]=1
    if (( life > _ss_max_life )); then _ss_max_life=$life; fi
  done
  _ss_occ[origin_key]=$count
  return 0
}

_ss_compute_timing() {
  local min_frames event_min config_frames pop_step fade_step gap_step
  _ss_frame_delay=$(printf '0.%03d' $((1000 / _ss_fps)))
  _ss_burst_frame=3

  pop_step=$((_ss_fps * 10 / 100))
  if (( pop_step < 1 )); then pop_step=1; fi
  if (( pop_step > 4 )); then pop_step=4; fi
  fade_step=$((_ss_fps * 12 / 100))
  if (( fade_step < 3 )); then fade_step=3; fi
  gap_step=$((_ss_fps * 12 / 100))
  if (( gap_step < 3 )); then gap_step=3; fi
  _ss_pop_step=$pop_step

  _ss_check_frame=$((_ss_burst_frame + _ss_fps * 55 / 100))
  if (( _ss_check_frame < _ss_burst_frame + 6 )); then
    _ss_check_frame=$((_ss_burst_frame + 6))
  fi

  _ss_group1_dim=$((_ss_check_frame + 3 * pop_step + gap_step))
  _ss_group1_normal=$((_ss_group1_dim + fade_step))
  _ss_group2_dim=$((_ss_group1_normal + gap_step))
  _ss_group2_normal=$((_ss_group2_dim + fade_step))
  _ss_pulse_frame=$((_ss_group2_normal + gap_step))
  _ss_pulse_end=$((_ss_pulse_frame + fade_step))

  event_min=$((_ss_pulse_end + _ss_fps / 2))
  min_frames=$((_ss_burst_frame + _ss_max_life + _ss_fps / 6))
  if (( event_min > min_frames )); then min_frames=$event_min; fi
  config_frames=$((_ss_duration * _ss_fps / 1000))
  _ss_total_frames=$config_frames
  if (( _ss_total_frames < min_frames )); then _ss_total_frames=$min_frames; fi
  return 0
}

_ss_compute_raw_timing() {
  local pop_step gap_step event_min min_frames config_frames
  _ss_frame_delay=$(printf '0.%03d' $((1000 / _ss_fps)))
  _ss_burst_frame=3

  pop_step=$((_ss_fps * 10 / 100))
  if (( pop_step < 1 )); then pop_step=1; fi
  if (( pop_step > 4 )); then pop_step=4; fi
  gap_step=$((_ss_fps * 12 / 100))
  if (( gap_step < 3 )); then gap_step=3; fi
  _ss_pop_step=$pop_step

  _ss_raw_check_frame=0
  _ss_raw_block_frame=$((_ss_burst_frame + _ss_fps * 55 / 100))
  if (( _ss_raw_block_frame < _ss_burst_frame + 6 )); then
    _ss_raw_block_frame=$((_ss_burst_frame + 6))
  fi
  if (( _ss_raw_has_check )); then
    _ss_raw_check_frame=$_ss_raw_block_frame
    _ss_raw_block_frame=$((_ss_raw_check_frame + 3 * pop_step + gap_step))
  fi

  event_min=$((_ss_raw_block_frame + _ss_fps / 2))
  min_frames=$((_ss_burst_frame + _ss_max_life + _ss_fps / 6))
  if (( event_min > min_frames )); then min_frames=$event_min; fi
  config_frames=$((_ss_duration * _ss_fps / 1000))
  _ss_total_frames=$config_frames
  if (( _ss_total_frames < min_frames )); then _ss_total_frames=$min_frames; fi
  return 0
}

_ss_margin_cell() {
  local row=$1 col=$2 key
  if (( row < 1 || row > _ss_lines || col < 1 || col > _ss_cols - 1 )); then
    return 0
  fi
  key=$((row * _ss_stride + col))
  if (( ${_ss_mask[$key]:-0} == 0 )); then
    printf '%s%s[%d;%dH ' "$_ss_reset" "$_ss_esc" "$row" "$col"
    _ss_mask[key]=1
  fi
  return 0
}

_ss_put() {
  local row=$1 col=$2 pre=$3 pre_style=$4 text=$5 style=$6
  local i key maxlen plen tlen start width
  if (( row < 1 || row > _ss_lines )); then return 0; fi
  if (( col < 1 || col > _ss_cols )); then return 0; fi
  maxlen=$((_ss_cols - col))
  if (( maxlen < 1 )); then return 0; fi

  plen=${#pre}
  tlen=${#text}
  if (( plen > maxlen )); then
    pre=${pre:0:maxlen}
    text=""
    plen=$maxlen
    tlen=0
  elif (( plen + tlen > maxlen )); then
    text=${text:0:maxlen - plen}
    tlen=$((maxlen - plen))
  fi
  width=$((plen + tlen))

  # Keep a quiet margin on each side so confetti does not look attached to text.
  _ss_margin_cell "$row" $((col - 1))
  _ss_margin_cell "$row" $((col - 2))

  printf '%s%s[%d;%dH' "$_ss_reset" "$_ss_esc" "$row" "$col"
  if (( plen > 0 )); then
    printf '%s%s%s' "$pre_style" "$pre" "$_ss_reset"
    for ((i=0; i<plen; i++)); do
      key=$((row * _ss_stride + col + i))
      _ss_mask[key]=1
    done
  fi
  if (( tlen > 0 )); then
    printf '%s%s%s' "$style" "$text" "$_ss_reset"
    start=$((col + plen))
    for ((i=0; i<tlen; i++)); do
      key=$((row * _ss_stride + start + i))
      _ss_mask[key]=1
    done
  fi
  if (( width > 0 )); then
    _ss_margin_cell "$row" $((col + width))
    _ss_margin_cell "$row" $((col + width + 1))
  fi
  return 0
}

_ss_put_raw() {
  local row=$1 col=$2 raw=$3
  local i key maxlen plen out
  if (( row < 1 || row > _ss_lines )); then return 0; fi
  if (( col < 1 || col > _ss_cols )); then return 0; fi
  maxlen=$((_ss_cols - col))
  if (( maxlen < 1 )); then return 0; fi

  if (( _ss_color )); then
    _ss_clip_raw "$raw" "$maxlen"
    out=$_ss_clipped
    plen=$_ss_clipped_len
  else
    _ss_plain_raw "$raw" "$maxlen"
    out=$_ss_plain
    plen=$_ss_plain_len
  fi
  if (( plen == 0 )); then return 0; fi

  _ss_margin_cell "$row" $((col - 1))
  _ss_margin_cell "$row" $((col - 2))
  printf '%s%s[%d;%dH%s%s' "$_ss_reset" "$_ss_esc" "$row" "$col" "$out" "$_ss_reset"
  for ((i=0; i<plen; i++)); do
    key=$((row * _ss_stride + col + i))
    _ss_mask[key]=1
  done
  _ss_margin_cell "$row" $((col + plen))
  _ss_margin_cell "$row" $((col + plen + 1))
  return 0
}

_ss_release_cell() {
  local key=$1 c
  if (( key <= 0 )); then return 0; fi
  c=$(( ${_ss_occ[$key]:-0} - 1 ))
  if (( c <= 0 )); then
    _ss_occ[key]=0
    if (( ${_ss_mask[$key]:-0} == 0 )); then
      _ss_frame_buf+="${_ss_reset}${_ss_esc}[$((key / _ss_stride));$((key % _ss_stride))H "
    fi
  else
    _ss_occ[key]=$c
  fi
  return 0
}

_ss_update_particles() {
  local i age life x y vx vy oldkey newkey ci ch c
  for ((i=0; i<_ss_particle_count; i++)); do
    if (( _ss_p_alive[i] == 0 )); then continue; fi
    age=$((_ss_p_age[i] + 1))
    life=${_ss_p_life[i]}
    x=${_ss_p_x[i]}
    y=${_ss_p_y[i]}
    oldkey=$(( (y / 100) * _ss_stride + (x / 100) ))

    if (( age >= life )); then
      _ss_p_alive[i]=0
      _ss_p_age[i]=$age
      _ss_release_cell "$oldkey"
      continue
    fi

    vx=$((_ss_p_vx[i] * _ss_drag / 100))
    vy=$((_ss_p_vy[i] + _ss_p_g[i]))
    x=$((x + vx + _ss_wobble[(age + _ss_p_wob[i]) % 8]))
    y=$((y + vy))
    _ss_p_vx[i]=$vx
    _ss_p_vy[i]=$vy
    _ss_p_x[i]=$x
    _ss_p_y[i]=$y
    _ss_p_age[i]=$age

    # Leave a one-cell margin: writing the bottom-right cell can scroll.
    if (( x < 100 || x > (_ss_cols - 1) * 100 || y < 100 || y > (_ss_lines - 1) * 100 )); then
      _ss_p_alive[i]=0
      _ss_release_cell "$oldkey"
      continue
    fi

    newkey=$(( (y / 100) * _ss_stride + (x / 100) ))
    if (( newkey != oldkey )); then
      _ss_release_cell "$oldkey"
      _ss_occ[newkey]=$(( ${_ss_occ[$newkey]:-0} + 1 ))
    fi

    if (( ${_ss_mask[$newkey]:-0} == 0 )); then
      ci=${_ss_p_color[i]}
      if (( age * 10 >= life * 9 )); then
        c="${_ss_c_dim}${_ss_conf_muted[ci]}"
      elif (( age * 10 >= life * 7 )); then
        c=${_ss_conf_muted[ci]}
      else
        c=${_ss_conf_bright[ci]}
      fi
      ch=${_ss_p_char[i]}
      _ss_frame_buf+="${_ss_reset}${_ss_esc}[$((newkey / _ss_stride));$((newkey % _ss_stride))H${c}${ch}"
    fi
  done
  _ss_frame_buf+="$_ss_reset"
  return 0
}

_ss_draw_group() {
  local group=$1 dim=$2 i n=${#_ss_l_text[@]} pre_style style
  for ((i=0; i<n; i++)); do
    if (( _ss_l_stage[i] == group )); then
      if [[ -n ${_ss_l_pre[i]} || -n ${_ss_l_text[i]} ]]; then
        pre_style=${_ss_l_pre_style[i]}
        style=${_ss_l_style[i]}
        if (( dim )); then
          pre_style="${_ss_c_dim}${pre_style}"
          style="${_ss_c_dim}${style}"
        fi
        _ss_put "${_ss_l_row[i]}" "${_ss_l_col[i]}" \
          "${_ss_l_pre[i]}" "$pre_style" \
          "${_ss_l_text[i]}" "$style"
      fi
    fi
  done
  return 0
}

_ss_draw_check_pop() {
  local frame=$1 ch style key
  if (( _ss_check_row < 1 || _ss_check_col < 1 )); then return 0; fi
  key=$((_ss_check_row * _ss_stride + _ss_check_col))
  _ss_mask[key]=1
  _ss_margin_cell "$_ss_check_row" $((_ss_check_col - 1))
  _ss_margin_cell "$_ss_check_row" $((_ss_check_col - 2))
  _ss_margin_cell "$_ss_check_row" $((_ss_check_col + 1))
  _ss_margin_cell "$_ss_check_row" $((_ss_check_col + 2))
  if (( frame == 0 )); then
    ch="·"
    style="${_ss_c_dim}${_ss_c_green_bold}"
  elif (( frame == 1 )); then
    ch="+"
    style="$_ss_c_green_bold"
  else
    ch="$_ss_check"
    style="$_ss_c_green_bold"
  fi
  if (( ! _ss_unicode )); then
    if (( frame == 0 )); then ch="."; elif (( frame == 1 )); then ch="*"; fi
  fi
  printf '%s%s[%d;%dH%s%s%s' "$_ss_reset" "$_ss_esc" \
    "$_ss_check_row" "$_ss_check_col" "$style" "$ch" "$_ss_reset"
  return 0
}

_ss_finish_check() {
  local i=$_ss_check_line
  if (( i >= 0 )); then
    _ss_put "${_ss_l_row[i]}" "${_ss_l_col[i]}" \
      "${_ss_l_pre[i]}" "${_ss_l_pre_style[i]}" \
      "${_ss_l_text[i]}" "${_ss_l_style[i]}"
  fi
  return 0
}

_ss_pulse_command() {
  local i n=${#_ss_cmd_lines[@]} idx
  if (( n == 0 )); then return 0; fi
  for ((i=0; i<n; i++)); do
    idx=${_ss_cmd_lines[i]}
    _ss_put "${_ss_l_row[idx]}" "${_ss_l_col[idx]}" \
      "${_ss_l_pre[idx]}" "${_ss_l_pre_style[idx]}" \
      "${_ss_l_text[idx]}" "$_ss_c_command_pulse"
  done
  return 0
}

_ss_restore_command() {
  local i n=${#_ss_cmd_lines[@]} idx
  if (( n == 0 )); then return 0; fi
  for ((i=0; i<n; i++)); do
    idx=${_ss_cmd_lines[i]}
    _ss_put "${_ss_l_row[idx]}" "${_ss_l_col[idx]}" \
      "${_ss_l_pre[idx]}" "${_ss_l_pre_style[idx]}" \
      "${_ss_l_text[idx]}" "$_ss_c_command"
  done
  return 0
}

_ss_finalize_reveals() {
  if (( _ss_check_phase < 3 )); then
    _ss_finish_check
    _ss_check_phase=3
  fi
  if (( _ss_group1_phase < 2 )); then
    _ss_draw_group 1 0
    _ss_group1_phase=2
  fi
  if (( _ss_group2_phase < 2 )); then
    _ss_draw_group 2 0
    _ss_group2_phase=2
  fi
  if (( _ss_pulse_phase < 2 )); then
    _ss_restore_command
    _ss_pulse_phase=2
  fi
  return 0
}

_ss_draw_anticipation() {
  local frame=$1 ch style
  if (( frame == 1 )); then
    ch="•"
    style="$_ss_c_green_bold"
  else
    ch="·"
    style="$_ss_c_dim"
  fi
  if (( ! _ss_unicode )); then
    if (( frame == 1 )); then ch="*"; else ch="."; fi
  fi
  printf '%s%s[%d;%dH%s%s%s' "$_ss_reset" "$_ss_esc" \
    "$_ss_origin_y" "$_ss_origin_x" "$style" "$ch" "$_ss_reset"
  return 0
}

_ss_clear_origin() {
  _ss_frame_buf+="${_ss_reset}${_ss_esc}[${_ss_origin_y};${_ss_origin_x}H "
  return 0
}

_ss_size_changed() {
  local r c
  r=$(tput lines) 2>/dev/null || return 1
  c=$(tput cols) 2>/dev/null || return 1
  [[ $r =~ ^[0-9]+$ && $c =~ ^[0-9]+$ ]] || return 1
  if (( r <= 0 || c <= 0 )); then return 1; fi
  (( r != _ss_lines || c != _ss_cols ))
}

_ss_run_animation() {
  local frame=0
  _ss_check_phase=0
  _ss_group1_phase=0
  _ss_group2_phase=0
  _ss_pulse_phase=0
  _ss_frame_buf=""
  while (( frame < _ss_total_frames )); do
    if (( frame > 0 && frame % 8 == 0 )); then
      if _ss_size_changed; then
        return 1
      fi
    fi

    _ss_frame_buf=""
    if (( frame < _ss_burst_frame )); then
      _ss_draw_anticipation "$frame"
    elif (( frame == _ss_burst_frame )); then
      _ss_clear_origin
      _ss_update_particles
    else
      _ss_update_particles
    fi
    if (( frame >= _ss_burst_frame )); then
      printf '%s' "$_ss_frame_buf"
      _ss_frame_buf=""
    fi

    if (( _ss_check_phase == 0 && frame >= _ss_check_frame )); then
      _ss_draw_check_pop 0
      _ss_check_phase=1
    fi
    if (( _ss_check_phase == 1 && frame >= _ss_check_frame + _ss_pop_step )); then
      _ss_draw_check_pop 1
      _ss_check_phase=2
    fi
    if (( _ss_check_phase == 2 && frame >= _ss_check_frame + 2 * _ss_pop_step )); then
      _ss_finish_check
      _ss_check_phase=3
    fi

    if (( _ss_group1_phase == 0 && frame >= _ss_group1_dim )); then
      _ss_draw_group 1 1
      _ss_group1_phase=1
    fi
    if (( _ss_group1_phase == 1 && frame >= _ss_group1_normal )); then
      _ss_draw_group 1 0
      _ss_group1_phase=2
    fi

    if (( _ss_group2_phase == 0 && frame >= _ss_group2_dim )); then
      _ss_draw_group 2 1
      _ss_group2_phase=1
    fi
    if (( _ss_group2_phase == 1 && frame >= _ss_group2_normal )); then
      _ss_draw_group 2 0
      _ss_group2_phase=2
    fi

    if (( _ss_pulse_phase == 0 && frame >= _ss_pulse_frame )); then
      _ss_pulse_command
      _ss_pulse_phase=1
    fi
    if (( _ss_pulse_phase == 1 && frame >= _ss_pulse_end )); then
      _ss_restore_command
      _ss_pulse_phase=2
    fi

    sleep "$_ss_frame_delay"
    frame=$((frame + 1))
  done

  _ss_finalize_reveals
  return 0
}

_ss_fw_init() {
  local i j count sparks total spacing margin max_target span
  local target_y target_x start_y dist rise speed launch burst
  local drag gbase

  count=$_ss_shells
  if (( _ss_cols < 60 || _ss_lines < 18 )); then count=$((count * 3 / 4)); fi
  if (( count < 2 )); then count=2; fi

  sparks=$_ss_sparks
  if (( _ss_cols < 45 || _ss_lines < 15 )); then sparks=$((sparks * 3 / 4)); fi
  if (( sparks < 8 )); then sparks=8; fi
  total=$((count * sparks))
  if (( total > 120 )); then
    sparks=$((120 / count))
    if (( sparks < 8 )); then sparks=8; fi
    total=$((count * sparks))
  fi
  _ss_fw_shell_count=$count
  _ss_fw_spark_count=$sparks
  _ss_particle_count=$total

  _ss_fw_s_x=(); _ss_fw_s_y=(); _ss_fw_s_target=(); _ss_fw_s_speed=()
  _ss_fw_s_launch=(); _ss_fw_s_burst=(); _ss_fw_s_state=(); _ss_fw_s_trail=()
  _ss_fw_s_prevkey=()
  _ss_p_x=(); _ss_p_y=(); _ss_p_vx=(); _ss_p_vy=(); _ss_p_g=()
  _ss_p_age=(); _ss_p_life=(); _ss_p_char=(); _ss_p_color=()
  _ss_p_wob=(); _ss_p_alive=()
  _ss_occ=()
  _ss_mask=()

  drag=$((100 - 72 / _ss_fps)); if (( drag < 90 )); then drag=90; fi
  _ss_drag=$drag
  gbase=$((_ss_gravity * 24 * 24 / (_ss_fps * _ss_fps)))
  if (( gbase < 1 )); then gbase=1; fi
  _ss_gbase=$gbase
  _ss_max_life=$(( 30 * _ss_fps / 24 ))
  if (( _ss_max_life < 12 )); then _ss_max_life=12; fi

  margin=3
  if (( _ss_cols < 20 )); then margin=1; fi
  span=$((_ss_cols - 2 * margin))
  if (( span < 1 )); then span=1; fi
  spacing=$((_ss_fps * 3 / 10))
  if (( spacing < 2 )); then spacing=2; fi
  max_target=$((_ss_lines / 2 - 1))
  if (( max_target < 2 )); then max_target=2; fi

  _ss_first_burst=0
  _ss_last_burst=0
  start_y=$((_ss_lines - 1))
  if (( start_y < 2 )); then start_y=2; fi

  for ((i=0; i<count; i++)); do
    target_y=$(( 2 + RANDOM % (max_target - 1) ))
    target_x=$(( margin + 1 + RANDOM % span ))
    if (( target_x < 2 )); then target_x=2; fi
    if (( target_x > _ss_cols - 2 )); then target_x=$((_ss_cols - 2)); fi
    speed=$(( (140 + RANDOM % 81) * 24 / _ss_fps ))
    if (( speed < 30 )); then speed=30; fi
    dist=$(( (start_y - target_y) * 100 ))
    if (( dist < 100 )); then dist=100; fi
    rise=$(( (dist + speed - 1) / speed ))
    if (( rise < 3 )); then rise=3; fi
    launch=$(( 2 + i * spacing ))
    burst=$(( launch + rise ))

    _ss_fw_s_x[i]=$((target_x * 100))
    _ss_fw_s_y[i]=$((start_y * 100))
    _ss_fw_s_target[i]=$target_y
    _ss_fw_s_speed[i]=$speed
    _ss_fw_s_launch[i]=$launch
    _ss_fw_s_burst[i]=$burst
    _ss_fw_s_state[i]=0
    _ss_fw_s_trail[i]=0
    _ss_fw_s_prevkey[i]=0

    if (( _ss_first_burst == 0 || burst < _ss_first_burst )); then
      _ss_first_burst=$burst
    fi
    if (( burst > _ss_last_burst )); then _ss_last_burst=$burst; fi
  done

  for ((j=0; j<total; j++)); do
    _ss_p_x[j]=0; _ss_p_y[j]=0; _ss_p_vx[j]=0; _ss_p_vy[j]=0
    _ss_p_g[j]=$gbase; _ss_p_age[j]=0; _ss_p_life[j]=1
    _ss_p_char[j]=${_ss_chars[0]}
    _ss_p_color[j]=0; _ss_p_wob[j]=0; _ss_p_alive[j]=0
  done
  return 0
}

_ss_fw_compute_timing() {
  local min_frames event_min config_frames pop_step fade_step gap_step
  _ss_frame_delay=$(printf '0.%03d' $((1000 / _ss_fps)))

  pop_step=$((_ss_fps * 10 / 100))
  if (( pop_step < 1 )); then pop_step=1; fi
  if (( pop_step > 4 )); then pop_step=4; fi
  fade_step=$((_ss_fps * 12 / 100))
  if (( fade_step < 3 )); then fade_step=3; fi
  gap_step=$((_ss_fps * 12 / 100))
  if (( gap_step < 3 )); then gap_step=3; fi
  _ss_pop_step=$pop_step

  _ss_check_frame=$((_ss_first_burst + 2))
  if (( _ss_check_frame < 4 )); then _ss_check_frame=4; fi

  _ss_group1_dim=$((_ss_check_frame + 3 * pop_step + gap_step))
  _ss_group1_normal=$((_ss_group1_dim + fade_step))
  _ss_group2_dim=$((_ss_group1_normal + gap_step))
  _ss_group2_normal=$((_ss_group2_dim + fade_step))
  _ss_pulse_frame=$((_ss_group2_normal + gap_step))
  _ss_pulse_end=$((_ss_pulse_frame + fade_step))

  event_min=$((_ss_pulse_end + _ss_fps / 2))
  min_frames=$((_ss_last_burst + _ss_max_life + _ss_fps / 6))
  if (( event_min > min_frames )); then min_frames=$event_min; fi
  config_frames=$((_ss_duration * _ss_fps / 1000))
  _ss_total_frames=$config_frames
  if (( _ss_total_frames < min_frames )); then _ss_total_frames=$min_frames; fi
  return 0
}

_ss_fw_compute_block_timing() {
  local min_frames event_min config_frames pop_step gap_step
  _ss_frame_delay=$(printf '0.%03d' $((1000 / _ss_fps)))

  pop_step=$((_ss_fps * 10 / 100))
  if (( pop_step < 1 )); then pop_step=1; fi
  if (( pop_step > 4 )); then pop_step=4; fi
  gap_step=$((_ss_fps * 12 / 100))
  if (( gap_step < 3 )); then gap_step=3; fi
  _ss_pop_step=$pop_step

  _ss_raw_check_frame=0
  _ss_raw_block_frame=$((_ss_first_burst + _ss_fps * 55 / 100))
  if (( _ss_raw_block_frame < _ss_first_burst + 6 )); then
    _ss_raw_block_frame=$((_ss_first_burst + 6))
  fi
  if (( _ss_raw_has_check )); then
    _ss_raw_check_frame=$_ss_raw_block_frame
    _ss_raw_block_frame=$((_ss_raw_check_frame + 3 * pop_step + gap_step))
  fi

  event_min=$((_ss_raw_block_frame + _ss_fps / 2))
  min_frames=$((_ss_last_burst + _ss_max_life + _ss_fps / 6))
  if (( event_min > min_frames )); then min_frames=$event_min; fi
  config_frames=$((_ss_duration * _ss_fps / 1000))
  _ss_total_frames=$config_frames
  if (( _ss_total_frames < min_frames )); then _ss_total_frames=$min_frames; fi
  return 0
}

_ss_fw_update_shells() {
  local i state y x newkey oldkey trail_row trail_key
  for ((i=0; i<_ss_fw_shell_count; i++)); do
    state=${_ss_fw_s_state[i]}
    if (( state == 0 )); then
      if (( _ss_frame < _ss_fw_s_launch[i] )); then continue; fi
      state=1
      _ss_fw_s_state[i]=1
      _ss_fw_s_y[i]=$(( (_ss_lines - 1) * 100 ))
    fi
    if (( state == 2 )); then continue; fi

    oldkey=${_ss_fw_s_prevkey[i]:-0}
    if (( oldkey > 0 )); then
      _ss_release_cell "$oldkey"
      _ss_fw_s_prevkey[i]=0
    fi
    trail_key=${_ss_fw_s_trail[i]:-0}
    if (( trail_key > 0 )); then
      _ss_release_cell "$trail_key"
      _ss_fw_s_trail[i]=0
    fi

    y=${_ss_fw_s_y[i]}
    x=${_ss_fw_s_x[i]}
    y=$(( y - _ss_fw_s_speed[i] ))
    _ss_fw_s_y[i]=$y

    if (( y <= _ss_fw_s_target[i] * 100 )); then
      _ss_fw_s_y[i]=$(( _ss_fw_s_target[i] * 100 ))
      _ss_fw_s_state[i]=2
      _ss_fw_explode_shell "$i"
      continue
    fi

    newkey=$(( (y / 100) * _ss_stride + (x / 100) ))
    _ss_occ[newkey]=$(( ${_ss_occ[$newkey]:-0} + 1 ))
    if (( ${_ss_mask[$newkey]:-0} == 0 )); then
      _ss_frame_buf+="${_ss_reset}${_ss_esc}[$((newkey / _ss_stride));$((newkey % _ss_stride))H${_ss_c_rocket}${_ss_rocket}${_ss_reset}"
    fi
    _ss_fw_s_prevkey[i]=$newkey

    trail_row=$(( y / 100 + 1 ))
    if (( trail_row >= 1 && trail_row <= _ss_lines - 1 )); then
      trail_key=$(( trail_row * _ss_stride + (x / 100) ))
      _ss_occ[trail_key]=$(( ${_ss_occ[$trail_key]:-0} + 1 ))
      if (( ${_ss_mask[$trail_key]:-0} == 0 )); then
        _ss_frame_buf+="${_ss_reset}${_ss_esc}[${trail_row};$((x / 100))H${_ss_c_dim}${_ss_trail_char}${_ss_reset}"
      fi
      _ss_fw_s_trail[i]=$trail_key
    fi
  done
  return 0
}

_ss_fw_explode_shell() {
  local i=$1 base j k idx speed vx vy life g px py key
  base=$((i * _ss_fw_spark_count))
  for ((j=0; j<_ss_fw_spark_count; j++)); do
    k=$((base + j))
    idx=$(( (j * 16 / _ss_fw_spark_count + RANDOM % 2) % 16 ))
    speed=$(( 70 + RANDOM % 71 ))
    vx=$(( _ss_dir_vx[idx] * speed * 24 / 100 / _ss_fps ))
    vy=$(( _ss_dir_vy[idx] * speed * 24 / 100 / _ss_fps ))
    life=$(( (16 + RANDOM % 15) * _ss_fps / 24 ))
    if (( life < 8 )); then life=8; fi
    g=$(( _ss_gbase + RANDOM % 3 - 1 ))
    if (( g < 1 )); then g=1; fi

    px=$(( _ss_fw_s_x[i] + RANDOM % 41 - 20 ))
    py=$(( _ss_fw_s_y[i] + RANDOM % 21 - 10 ))
    if (( px < 100 )); then px=100; fi
    if (( px > (_ss_cols - 1) * 100 )); then px=$(( (_ss_cols - 1) * 100 )); fi
    if (( py < 100 )); then py=100; fi
    if (( py > (_ss_lines - 1) * 100 )); then py=$(( (_ss_lines - 1) * 100 )); fi

    _ss_p_x[k]=$px
    _ss_p_y[k]=$py
    _ss_p_vx[k]=$vx
    _ss_p_vy[k]=$vy
    _ss_p_g[k]=$g
    _ss_p_age[k]=0
    _ss_p_life[k]=$life
    _ss_p_char[k]=${_ss_chars[RANDOM % ${#_ss_chars[@]}]}
    _ss_p_color[k]=$(( RANDOM % _ss_palette_n ))
    _ss_p_wob[k]=$(( RANDOM % 8 ))
    _ss_p_alive[k]=1

    key=$(( (py / 100) * _ss_stride + (px / 100) ))
    _ss_occ[key]=$(( ${_ss_occ[$key]:-0} + 1 ))
  done
  return 0
}

_ss_fw_clear_effects() {
  local i key
  _ss_frame_buf=""
  for ((i=0; i<_ss_particle_count; i++)); do
    if (( ${_ss_p_alive[i]:-0} == 0 )); then continue; fi
    key=$(( (_ss_p_y[i] / 100) * _ss_stride + (_ss_p_x[i] / 100) ))
    _ss_release_cell "$key"
    _ss_p_alive[i]=0
  done
  for ((i=0; i<_ss_fw_shell_count; i++)); do
    key=${_ss_fw_s_prevkey[i]:-0}
    if (( key > 0 )); then
      _ss_release_cell "$key"
      _ss_fw_s_prevkey[i]=0
    fi
    key=${_ss_fw_s_trail[i]:-0}
    if (( key > 0 )); then
      _ss_release_cell "$key"
      _ss_fw_s_trail[i]=0
    fi
    _ss_fw_s_state[i]=2
  done
  printf '%s' "$_ss_frame_buf"
  _ss_frame_buf=""
  return 0
}

_ss_fw_run_animation() {
  local frame=0
  _ss_check_phase=0
  _ss_group1_phase=0
  _ss_group2_phase=0
  _ss_pulse_phase=0
  _ss_frame_buf=""
  while (( frame < _ss_total_frames )); do
    if (( frame > 0 && frame % 8 == 0 )); then
      if _ss_size_changed; then
        return 1
      fi
    fi

    _ss_frame_buf=""
    _ss_frame=$frame
    _ss_fw_update_shells
    _ss_update_particles
    printf '%s' "$_ss_frame_buf"
    _ss_frame_buf=""

    if (( _ss_check_phase == 0 && frame >= _ss_check_frame )); then
      _ss_draw_check_pop 0
      _ss_check_phase=1
    fi
    if (( _ss_check_phase == 1 && frame >= _ss_check_frame + _ss_pop_step )); then
      _ss_draw_check_pop 1
      _ss_check_phase=2
    fi
    if (( _ss_check_phase == 2 && frame >= _ss_check_frame + 2 * _ss_pop_step )); then
      _ss_finish_check
      _ss_check_phase=3
    fi

    if (( _ss_group1_phase == 0 && frame >= _ss_group1_dim )); then
      _ss_draw_group 1 1
      _ss_group1_phase=1
    fi
    if (( _ss_group1_phase == 1 && frame >= _ss_group1_normal )); then
      _ss_draw_group 1 0
      _ss_group1_phase=2
    fi

    if (( _ss_group2_phase == 0 && frame >= _ss_group2_dim )); then
      _ss_draw_group 2 1
      _ss_group2_phase=1
    fi
    if (( _ss_group2_phase == 1 && frame >= _ss_group2_normal )); then
      _ss_draw_group 2 0
      _ss_group2_phase=2
    fi

    if (( _ss_pulse_phase == 0 && frame >= _ss_pulse_frame )); then
      _ss_pulse_command
      _ss_pulse_phase=1
    fi
    if (( _ss_pulse_phase == 1 && frame >= _ss_pulse_end )); then
      _ss_restore_command
      _ss_pulse_phase=2
    fi

    sleep "$_ss_frame_delay"
    frame=$((frame + 1))
  done

  _ss_fw_clear_effects
  _ss_finalize_reveals
  return 0
}

_ss_fw_run_block_animation() {
  local frame=0 check_phase=0 block_drawn=0
  _ss_frame_buf=""
  while (( frame < _ss_total_frames )); do
    if (( frame > 0 && frame % 8 == 0 )); then
      if _ss_size_changed; then
        return 1
      fi
    fi

    _ss_frame_buf=""
    _ss_frame=$frame
    _ss_fw_update_shells
    _ss_update_particles
    printf '%s' "$_ss_frame_buf"
    _ss_frame_buf=""

    if (( _ss_raw_has_check )); then
      if (( check_phase == 0 && frame >= _ss_raw_check_frame )); then
        _ss_draw_check_pop 0
        check_phase=1
      fi
      if (( check_phase == 1 && frame >= _ss_raw_check_frame + _ss_pop_step )); then
        _ss_draw_check_pop 1
        check_phase=2
      fi
      if (( check_phase == 2 && frame >= _ss_raw_check_frame + 2 * _ss_pop_step )); then
        _ss_draw_check_pop 2
        check_phase=3
      fi
    fi

    if (( block_drawn == 0 && frame >= _ss_raw_block_frame )); then
      _ss_paint_raw_block
      block_drawn=1
    fi

    sleep "$_ss_frame_delay"
    frame=$((frame + 1))
  done

  _ss_fw_clear_effects
  if (( _ss_raw_has_check && check_phase < 3 )); then
    _ss_draw_check_pop 2
  fi
  if (( block_drawn == 0 )); then
    _ss_paint_raw_block
  fi
  return 0
}

_ss_run_raw_animation() {
  local frame=0 check_phase=0 block_drawn=0
  _ss_frame_buf=""
  while (( frame < _ss_total_frames )); do
    if (( frame > 0 && frame % 8 == 0 )); then
      if _ss_size_changed; then
        return 1
      fi
    fi

    _ss_frame_buf=""
    if (( frame < _ss_burst_frame )); then
      _ss_draw_anticipation "$frame"
    elif (( frame == _ss_burst_frame )); then
      _ss_clear_origin
      _ss_update_particles
    else
      _ss_update_particles
    fi
    if (( frame >= _ss_burst_frame )); then
      printf '%s' "$_ss_frame_buf"
      _ss_frame_buf=""
    fi

    if (( _ss_raw_has_check )); then
      if (( check_phase == 0 && frame >= _ss_raw_check_frame )); then
        _ss_draw_check_pop 0
        check_phase=1
      fi
      if (( check_phase == 1 && frame >= _ss_raw_check_frame + _ss_pop_step )); then
        _ss_draw_check_pop 1
        check_phase=2
      fi
      if (( check_phase == 2 && frame >= _ss_raw_check_frame + 2 * _ss_pop_step )); then
        _ss_draw_check_pop 2
        check_phase=3
      fi
    fi

    if (( block_drawn == 0 && frame >= _ss_raw_block_frame )); then
      _ss_paint_raw_block
      block_drawn=1
    fi

    sleep "$_ss_frame_delay"
    frame=$((frame + 1))
  done

  if (( _ss_raw_has_check && check_phase < 3 )); then
    _ss_draw_check_pop 2
  fi
  if (( block_drawn == 0 )); then
    _ss_paint_raw_block
  fi
  return 0
}

_ss_setup_terminal() {
  _ss_old_exit=$(trap -p EXIT) || _ss_old_exit=""
  _ss_old_int=$(trap -p INT) || _ss_old_int=""
  _ss_old_term=$(trap -p TERM) || _ss_old_term=""
  _ss_old_hup=$(trap -p HUP) || _ss_old_hup=""
  _ss_traps_set=1

  trap '_ss_cleanup' EXIT
  trap '_ss_signal 130' INT
  trap '_ss_signal 143' TERM
  trap '_ss_signal 129' HUP

  _ss_animating=1
  printf '%s%s' "$_ss_clear_screen" "$_ss_reset"
  _ss_cursor_hidden=1
  printf '%s' "$_ss_civis"
  return 0
}

_ss_park_cursor() {
  local row=$_ss_lines
  if (( row < 1 )); then row=1; fi
  if [[ -n $_ss_reset ]]; then printf '%s' "$_ss_reset"; fi
  printf '%s[%d;1H' "$_ss_esc" "$row"
  if (( _ss_cursor_hidden )); then
    if [[ -n $_ss_cnorm ]]; then
      printf '%s' "$_ss_cnorm"
    else
      printf '%s' $'\e[?25h'
    fi
    _ss_cursor_hidden=0
  fi
  return 0
}

_ss_finish() {
  _ss_animating=0
  _ss_park_cursor
  return 0
}

_ss_clear_and_paint() {
  printf '%s%s' "$_ss_clear_screen" "$_ss_reset"
  _ss_detect_size
  _ss_prepare_static
  if (( _ss_layout_ok )); then
    _ss_paint_layout
  else
    _ss_print_minimal
  fi
  _ss_finish
  return 0
}

_ss_clear_and_paint_raw() {
  printf '%s%s' "$_ss_clear_screen" "$_ss_reset"
  _ss_detect_size
  _ss_prepare_raw
  if (( _ss_raw_layout_ok )); then
    _ss_print_raw_block
  else
    _ss_print_raw_minimal
  fi
  _ss_finish
  return 0
}

_ss_cleanup() {
  if (( _ss_animating )); then
    printf '%s%s' "$_ss_clear_screen" "$_ss_reset"
    _ss_animating=0
  fi
  _ss_park_cursor
  return 0
}

_ss_signal() {
  _ss_cleanup
  trap - EXIT INT TERM HUP
  exit "$1"
}

_ss_restore_traps() {
  if (( ! _ss_traps_set )); then return 0; fi
  trap - EXIT INT TERM HUP
  if [[ -n $_ss_old_exit ]]; then eval "$_ss_old_exit"; fi
  if [[ -n $_ss_old_int ]]; then eval "$_ss_old_int"; fi
  if [[ -n $_ss_old_term ]]; then eval "$_ss_old_term"; fi
  if [[ -n $_ss_old_hup ]]; then eval "$_ss_old_hup"; fi
  _ss_traps_set=0
  return 0
}

_ss_raw_parse_args() {
  _ss_raw_lines=()
  _ss_raw_has_check=0
  _ss_raw_center_lines=0
  _ss_force_static=0

  while (( $# > 0 )); do
    case $1 in
      --effect)
        if (( $# < 2 )); then
          printf 'show_success_block: --effect needs a value\n' >&2
          return 1
        fi
        _ss_effect=$2
        shift 2
        ;;
      --check) _ss_raw_has_check=1; shift ;;
      --center-lines) _ss_raw_center_lines=1; shift ;;
      --static) _ss_force_static=1; shift ;;
      -h|--help) _ss_confetti_usage; return 2 ;;
      --)
        shift
        while (( $# > 0 )); do _ss_raw_lines+=("$1"); shift; done
        break
        ;;
      -*)
        printf 'show_success_block: unknown option: %s\n' "$1" >&2
        return 1
        ;;
      *)
        _ss_raw_lines+=("$1")
        shift
        ;;
    esac
  done

  if (( ${#_ss_raw_lines[@]} == 0 )); then
    printf 'show_success_block: at least one line is required\n' >&2
    return 1
  fi
  return 0
}

show_success_block() {
  local rc=0 old_cols old_lines
  _ss_effect=confetti
  _ss_raw_parse_args "$@" || rc=$?
  if (( rc == 2 )); then return 0; fi
  if (( rc != 0 )); then return 1; fi

  _ss_config
  _ss_detect

  if (( ! _ss_tty )); then
    _ss_log_raw
    return 0
  fi

  _ss_prepare_raw

  if (( ! _ss_raw_layout_ok )); then
    _ss_print_raw_minimal
    return 0
  fi

  if (( _ss_force_static )) || (( ! _ss_can_animate )) || (( ! _ss_raw_animate_ok )); then
    _ss_print_raw_block
    return 0
  fi

  if [[ $_ss_effect == fireworks ]]; then
    _ss_fw_init
    _ss_fw_compute_block_timing
  else
    _ss_init_particles
    _ss_compute_raw_timing
  fi
  _ss_setup_terminal

  rc=0
  if [[ $_ss_effect == fireworks ]]; then
    _ss_fw_run_block_animation || rc=$?
  else
    _ss_run_raw_animation || rc=$?
  fi
  if (( rc != 0 )); then
    _ss_clear_and_paint_raw
    _ss_restore_traps
    return 0
  fi

  # Catch a resize that landed after the last in-loop check.
  old_cols=$_ss_cols
  old_lines=$_ss_lines
  _ss_detect_size
  if (( _ss_cols != old_cols || _ss_lines != old_lines )); then
    _ss_clear_and_paint_raw
  else
    _ss_finish
  fi
  _ss_restore_traps
  return 0
}

show_success_screen() {
  local rc=0
  _ss_effect=confetti
  _ss_parse_args "$@" || rc=$?
  if (( rc == 2 )); then return 0; fi
  if (( rc != 0 )); then return 1; fi

  _ss_config
  _ss_detect

  if (( ! _ss_tty )); then
    _ss_log
    return 0
  fi

  _ss_prepare_static

  if (( ! _ss_layout_ok )); then
    _ss_print_minimal
    return 0
  fi

  if (( _ss_force_static )) || (( ! _ss_can_animate )) || (( ! _ss_animate_ok )); then
    _ss_print_layout
    return 0
  fi

  if [[ $_ss_effect == fireworks ]]; then
    _ss_fw_init
    _ss_fw_compute_timing
  else
    _ss_init_particles
    _ss_compute_timing
  fi
  _ss_setup_terminal

  rc=0
  if [[ $_ss_effect == fireworks ]]; then
    _ss_fw_run_animation || rc=$?
  else
    _ss_run_animation || rc=$?
  fi
  if (( rc != 0 )); then
    _ss_clear_and_paint
    _ss_restore_traps
    return 0
  fi

  # Catch a resize that landed after the last in-loop check.
  local old_cols=$_ss_cols old_lines=$_ss_lines
  _ss_detect_size
  if (( _ss_cols != old_cols || _ss_lines != old_lines )); then
    _ss_clear_and_paint
  else
    _ss_finish
  fi
  _ss_restore_traps
  return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if (( $# > 0 )); then
    show_success_screen "$@"
  else
    show_success_screen \
      --title "Rivet Install complete" \
      --subtitle "Your OpenCode is now smarter." \
      --command "my-tool start" \
      --step "my-tool help" \
      --step "Read the documentation" \
      --step "Restart your shell"

      show_success_block --effect confetti --check \
        '  /\_/\  ' \
        ' ( o.o ) ' \
        '  > ^ <  '
  fi
fi



