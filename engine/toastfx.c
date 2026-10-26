/*
 * ToastFX - real-time voice changer for PipeWire
 *
 * Build:
 *   gcc toastfx.c -o toastfx $(pkg-config --cflags --libs libpipewire-0.3) -lm -lpthread
 *
 * Run it from a terminal and type a letter, then Enter:
 *   D = dry mic        R = radio          H = helmet comms
 *   B = robot          Q = quit
 *   Pressing the key of the active mode switches back to dry.
 *
 * Or run it in the background and control it with `toastfx-ctl` (see the
 * Makefile). It listens for the words dry, radio, helmet, robot and quit on a
 * command pipe, so desktop hotkeys can call `toastfx-ctl radio` etc.
 *
 * Optional environment variables, to pick devices by PipeWire node name:
 *   TOASTFX_INPUT   which microphone to capture from
 *   TOASTFX_OUTPUT  where to send the processed audio (e.g. a virtual mic)
 */

#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/audio/raw.h>

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* ------------------------------------------------------------------ */
/* Config                                                              */
/* ------------------------------------------------------------------ */

#define CHANNELS      2
#define SAMPLE_RATE   48000

#define RING_SIZE     65536                 /* samples, power of 2 */
#define RING_MASK     (RING_SIZE - 1)
/* If the ring holds more than this, drop the oldest audio so latency
 * can't creep up. 50 ms of stereo audio. */
#define MAX_LATENCY_SAMPLES (SAMPLE_RATE / 20 * CHANNELS)

#define TWO_PI        6.28318530717958647692f
#define PI_F          3.14159265358979323846f

/* Radio: "wartime field radio" - narrow, tinny, a little crunchy.
 * Chain: 2x high-pass 650 Hz -> 2x low-pass 2.3 kHz -> peak +7 dB @1.4 kHz
 *        -> compressor (-20 dB, 6:1) -> light 10-bit grit -> soft limiter.
 * Coefficients come from radio_init(). */
#define RADIO_HP_HZ          650.0f
#define RADIO_LP_HZ          2300.0f
#define RADIO_PK_HZ          1400.0f
#define RADIO_PK_Q           0.8f
#define RADIO_PK_DB          7.0f
#define RADIO_COMP_THRESH_DB -20.0f
#define RADIO_COMP_RATIO     6.0f
#define RADIO_ATTACK_MS      3.0f
#define RADIO_RELEASE_MS     70.0f
#define RADIO_MAKEUP_DB      4.0f
#define RADIO_GRIT_MIX       0.2f
#define RADIO_GRIT_STEP      (1.0f / 512.0f)   /* 10-bit steps */
#define RADIO_OUT_GAIN       3.6f              /* matches the level of the chosen test render */
#define RADIO_LIMIT          0.9f

/* Helmet: "squad comms through a helmet" (tuned against a Helldivers 2 clip)
 *
 * Chain: 2nd-order high-pass 280 Hz -> low-pass 3.8 kHz -> peak +3 dB @1.1 kHz
 *        -> peak +5 dB @2.6 kHz -> compressor (-24 dB, 4:1) -> short two-tap
 *        helmet echo (9 ms / 17 ms) -> soft limiter.
 * Coefficients are computed once by helmet_init(). Older version kept in
 * toastfx.recovery / the backup folder.
 */
#define HELMET_HP_HZ         280.0f
#define HELMET_LP_HZ         3800.0f
#define HELMET_PK1_HZ        1100.0f
#define HELMET_PK1_Q         1.2f
#define HELMET_PK1_DB        3.0f
#define HELMET_PK2_HZ        2600.0f
#define HELMET_PK2_Q         1.5f
#define HELMET_PK2_DB        5.0f
#define HELMET_COMP_THRESH_DB -24.0f
#define HELMET_COMP_RATIO    4.0f
#define HELMET_ATTACK_MS     5.0f
#define HELMET_RELEASE_MS    80.0f
#define HELMET_MAKEUP_DB     4.0f
#define HELMET_ECHO_1        432     /* samples = 9 ms  */
#define HELMET_ECHO_2        816     /* samples = 17 ms */
#define HELMET_ECHO_BUF      1024    /* power of 2, > largest tap */
#define HELMET_ECHO_G0       0.9f
#define HELMET_ECHO_G1       0.22f
#define HELMET_ECHO_G2       0.12f
#define HELMET_OUT_GAIN      1.5f
#define HELMET_LIMIT         0.9f

/* Robot */
#define ROBOT_CARRIER_HZ   55.0f   /* ring-mod frequency: lower = growlier */
#define ROBOT_HOLD         3       /* sample-and-hold factor (16 kHz grit) */
#define ROBOT_DRY_MIX      0.35f
#define ROBOT_RING_MIX     0.90f
#define ROBOT_COMB_DELAY   240     /* samples (5 ms) -> metallic ~200 Hz ring */
#define ROBOT_COMB_FB      0.55f
#define ROBOT_OUT_GAIN     0.60f

typedef enum {
    MODE_DRY = 0,
    MODE_RADIO,
    MODE_HELMET,
    MODE_ROBOT,
} fx_mode;

/* ------------------------------------------------------------------ */
/* Shared state                                                        */
/* ------------------------------------------------------------------ */

static float ring[RING_SIZE];
static _Atomic uint32_t head = 0;   /* written by capture, read by playback */
static _Atomic uint32_t tail = 0;   /* written by playback, read by capture */

static _Atomic int current_mode = MODE_DRY;

static struct pw_stream *input_stream;
static struct pw_stream *output_stream;
static struct pw_main_loop *main_loop;   /* so other threads can ask it to quit */

/* ------------------------------------------------------------------ */
/* DSP (only touched from the capture callback)                        */
/* ------------------------------------------------------------------ */

typedef struct { float x, y; } hp_state;        /* one-pole high-pass */
typedef struct { float low, band; } svf_state;  /* state-variable filter */

/* Everything that has to be remembered separately for each channel */
typedef struct {
    /* radio */
    float radio_z[5][2];     /* five biquads: HP, HP, LP, LP, peak */
    float radio_env_db;
    /* helmet */
    float helmet_z[4][2];    /* four biquads: HP, LP, peak 1.1k, peak 2.6k */
    float helmet_env_db;
    float helmet_echo[HELMET_ECHO_BUF];
    uint32_t helmet_echo_pos;
    /* robot */
    float robot_held;
    float robot_comb[ROBOT_COMB_DELAY];
} channel_state;

static struct {
    channel_state ch[CHANNELS];
    /* clocks shared by all channels, advanced once per frame */
    uint32_t robot_comb_pos, robot_hold_count;
    float robot_phase;
} dsp;

/* ----- small building blocks ----- */

static inline float soft_clip(float x, float knee)
{
    return x / (knee + fabsf(x));
}

static inline float onepole_hp(hp_state *s, float x, float alpha)
{
    float y = alpha * (s->y + x - s->x);
    s->x = x;
    s->y = y;
    return y;
}

static inline float onepole_lp(float *state, float x, float alpha)
{
    *state += alpha * (x - *state);
    return *state;
}

/* Band-pass output of a state-variable filter */
static inline float svf_band(svf_state *s, float x, float f, float q)
{
    float high = x - s->low - q * s->band;
    s->band += f * high;
    s->low  += f * s->band;
    return s->band;
}

static inline float wrap_phase(float p)
{
    return p >= TWO_PI ? p - TWO_PI : p;
}

/* ----- helmet ----- */

typedef struct { float b0, b1, b2, a1, a2; } biquad_coef;   /* a0 normalised to 1 */
static biquad_coef helmet_bq[4];
static float helmet_att, helmet_rel, helmet_makeup;

static biquad_coef bq_make(int kind, float hz, float q, float db)
{
    float w = TWO_PI * hz / SAMPLE_RATE, cw = cosf(w), sw = sinf(w);
    float al = sw / (2.0f * q), A = powf(10.0f, db / 40.0f);
    float b0, b1, b2, a0, a1, a2;
    if (kind == 0) {            /* high-pass */
        b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = b0;
        a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al;
    } else if (kind == 1) {     /* low-pass */
        b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = b0;
        a0 = 1 + al; a1 = -2 * cw; a2 = 1 - al;
    } else {                    /* peaking EQ */
        b0 = 1 + al * A; b1 = -2 * cw; b2 = 1 - al * A;
        a0 = 1 + al / A; a1 = -2 * cw; a2 = 1 - al / A;
    }
    biquad_coef c = { b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0 };
    return c;
}

static float helmet_g1 = HELMET_ECHO_G1, helmet_g2 = HELMET_ECHO_G2;

/* p = 0..1 intensity. 1.0 is the tuned sound; lower opens the band and fades echo/boosts. */
static void helmet_apply(float p)
{
    float hp = 150.0f  * powf(HELMET_HP_HZ / 150.0f,  p);
    float lp = 7000.0f * powf(HELMET_LP_HZ / 7000.0f, p);
    helmet_bq[0] = bq_make(0, hp, 0.7071f, 0);
    helmet_bq[1] = bq_make(1, lp, 0.7071f, 0);
    helmet_bq[2] = bq_make(2, HELMET_PK1_HZ, HELMET_PK1_Q, HELMET_PK1_DB * p);
    helmet_bq[3] = bq_make(2, HELMET_PK2_HZ, HELMET_PK2_Q, HELMET_PK2_DB * p);
    helmet_g1 = HELMET_ECHO_G1 * p;
    helmet_g2 = HELMET_ECHO_G2 * p;
}

static void helmet_init(void)
{
    helmet_apply(1.0f);
    helmet_att = 1.0f - expf(-1.0f / (HELMET_ATTACK_MS  * 0.001f * SAMPLE_RATE));
    helmet_rel = 1.0f - expf(-1.0f / (HELMET_RELEASE_MS * 0.001f * SAMPLE_RATE));
    helmet_makeup = powf(10.0f, HELMET_MAKEUP_DB / 20.0f);
}

static inline float bq_run(const biquad_coef *k, float *z, float x)
{
    float y = k->b0 * x + z[0];          /* transposed direct form II */
    z[0] = k->b1 * x - k->a1 * y + z[1];
    z[1] = k->b2 * x - k->a2 * y;
    return y;
}

static float fx_helmet(channel_state *c, float x)
{
    float y = x;
    for (int i = 0; i < 4; i++)
        y = bq_run(&helmet_bq[i], c->helmet_z[i], y);

    /* Compressor: level detector in dB, attack/release smoothing */
    float lvl_db = 20.0f * log10f(fabsf(y) + 1e-6f);
    float coef = lvl_db > c->helmet_env_db ? helmet_att : helmet_rel;
    c->helmet_env_db += coef * (lvl_db - c->helmet_env_db);
    float over = c->helmet_env_db - HELMET_COMP_THRESH_DB;
    float gain_db = over > 0 ? -over * (1.0f - 1.0f / HELMET_COMP_RATIO) : 0.0f;
    y *= powf(10.0f, gain_db / 20.0f) * helmet_makeup;

    /* Short helmet echo: two feed-forward taps */
    uint32_t p = c->helmet_echo_pos;
    c->helmet_echo[p & (HELMET_ECHO_BUF - 1)] = y;
    float d1 = c->helmet_echo[(p - HELMET_ECHO_1) & (HELMET_ECHO_BUF - 1)];
    float d2 = c->helmet_echo[(p - HELMET_ECHO_2) & (HELMET_ECHO_BUF - 1)];
    c->helmet_echo_pos = p + 1;
    y = (y * HELMET_ECHO_G0 + d1 * helmet_g1 + d2 * helmet_g2) * HELMET_OUT_GAIN;

    /* Soft limiter keeps peaks under control */
    return HELMET_LIMIT * tanhf(y / HELMET_LIMIT);
}

/* ----- radio ----- */

static biquad_coef radio_bq[5];
static float radio_att, radio_rel, radio_makeup;

static float radio_grit = RADIO_GRIT_MIX;

static void radio_apply(float p)
{
    float hp = 150.0f  * powf(RADIO_HP_HZ / 150.0f,  p);
    float lp = 6000.0f * powf(RADIO_LP_HZ / 6000.0f, p);
    radio_bq[0] = bq_make(0, hp, 0.7071f, 0);
    radio_bq[1] = bq_make(0, hp, 0.7071f, 0);
    radio_bq[2] = bq_make(1, lp, 0.7071f, 0);
    radio_bq[3] = bq_make(1, lp, 0.7071f, 0);
    radio_bq[4] = bq_make(2, RADIO_PK_HZ, RADIO_PK_Q, RADIO_PK_DB * p);
    radio_grit = RADIO_GRIT_MIX * p;
}

static void radio_init(void)
{
    radio_apply(1.0f);
    radio_att = 1.0f - expf(-1.0f / (RADIO_ATTACK_MS  * 0.001f * SAMPLE_RATE));
    radio_rel = 1.0f - expf(-1.0f / (RADIO_RELEASE_MS * 0.001f * SAMPLE_RATE));
    radio_makeup = powf(10.0f, RADIO_MAKEUP_DB / 20.0f);
}

static float fx_radio(channel_state *c, float x)
{
    float y = x;
    for (int i = 0; i < 5; i++)
        y = bq_run(&radio_bq[i], c->radio_z[i], y);

    float lvl_db = 20.0f * log10f(fabsf(y) + 1e-6f);
    float coef = lvl_db > c->radio_env_db ? radio_att : radio_rel;
    c->radio_env_db += coef * (lvl_db - c->radio_env_db);
    float over = c->radio_env_db - RADIO_COMP_THRESH_DB;
    float gain_db = over > 0 ? -over * (1.0f - 1.0f / RADIO_COMP_RATIO) : 0.0f;
    y *= powf(10.0f, gain_db / 20.0f) * radio_makeup;

    /* a little digital grit: blend in a coarsely quantised copy */
    float q = roundf(y / RADIO_GRIT_STEP) * RADIO_GRIT_STEP;
    y = y * (1.0f - radio_grit) + q * radio_grit;

    y *= RADIO_OUT_GAIN;
    return RADIO_LIMIT * tanhf(y / RADIO_LIMIT);
}

/* ----- live tweaks (Quick Tweaks sliders in the window) ----- */

static _Atomic int tw_radio = 100, tw_helmet = 100, tw_mix = 100, tw_ver = 0;
static float tw_mix_f = 1.0f;

static void tweaks_refresh(void)
{
    static int seen = -1;
    int v = atomic_load_explicit(&tw_ver, memory_order_acquire);
    if (v == seen)
        return;
    seen = v;
    radio_apply(atomic_load_explicit(&tw_radio, memory_order_relaxed) / 100.0f);
    helmet_apply(atomic_load_explicit(&tw_helmet, memory_order_relaxed) / 100.0f);
    tw_mix_f = atomic_load_explicit(&tw_mix, memory_order_relaxed) / 100.0f;
}

/* args look like "radio 60" / "helmet 80" / "mix 50" (0..100) */
static void tweak_command(const char *args)
{
    char name[16];
    int val;
    if (sscanf(args, "%15s %d", name, &val) != 2)
        return;
    if (val < 0) val = 0;
    if (val > 100) val = 100;
    if      (!strcmp(name, "radio"))  atomic_store(&tw_radio, val);
    else if (!strcmp(name, "helmet")) atomic_store(&tw_helmet, val);
    else if (!strcmp(name, "mix"))    atomic_store(&tw_mix, val);
    else return;
    atomic_fetch_add_explicit(&tw_ver, 1, memory_order_release);
}

/* ----- robot ----- */

/*
 *   1. sample-and-hold      -> gritty, low-fi digital edge
 *   2. ring modulation      -> classic inharmonic "Dalek" buzz
 *   3. short feedback comb  -> metallic, resonant tube sound
 *   4. soft clip            -> keeps it from blowing up
 *
 * `carrier` is the shared sine value for this frame; `refresh` says whether
 * this frame should grab a new sample for the hold stage.
 */
static float fx_robot(channel_state *c, float x, float carrier, int refresh)
{
    if (refresh)
        c->robot_held = x;
    float held = c->robot_held;

    float mixed = held * ROBOT_DRY_MIX + held * carrier * ROBOT_RING_MIX;

    float delayed = c->robot_comb[dsp.robot_comb_pos];
    float y = mixed + ROBOT_COMB_FB * delayed;
    c->robot_comb[dsp.robot_comb_pos] = y;

    return soft_clip(y * ROBOT_OUT_GAIN * 2.0f, 0.8f);
}

/* ----- one stereo frame in, one out ----- */

static void process_frame_raw(int mode, const float *in, float *out)
{
    switch (mode) {
    case MODE_RADIO:
        for (int ch = 0; ch < CHANNELS; ch++)
            out[ch] = fx_radio(&dsp.ch[ch], in[ch]);
        break;

    case MODE_HELMET:
        for (int ch = 0; ch < CHANNELS; ch++)
            out[ch] = fx_helmet(&dsp.ch[ch], in[ch]);
        break;

    case MODE_ROBOT: {
        float carrier = sinf(dsp.robot_phase);
        int refresh = (dsp.robot_hold_count == 0);

        for (int ch = 0; ch < CHANNELS; ch++)
            out[ch] = fx_robot(&dsp.ch[ch], in[ch], carrier, refresh);

        dsp.robot_phase = wrap_phase(dsp.robot_phase +
                                     TWO_PI * ROBOT_CARRIER_HZ / SAMPLE_RATE);
        dsp.robot_hold_count = (dsp.robot_hold_count + 1) % ROBOT_HOLD;
        dsp.robot_comb_pos = (dsp.robot_comb_pos + 1) % ROBOT_COMB_DELAY;
        break;
    }

    case MODE_DRY:
    default:
        for (int ch = 0; ch < CHANNELS; ch++)
            out[ch] = in[ch];
        break;
    }
}

static void process_frame(int mode, const float *in, float *out)
{
    tweaks_refresh();
    process_frame_raw(mode, in, out);
    if (mode != MODE_DRY && tw_mix_f < 0.999f)
        for (int ch = 0; ch < CHANNELS; ch++)
            out[ch] = in[ch] * (1.0f - tw_mix_f) + out[ch] * tw_mix_f;
}

/* ------------------------------------------------------------------ */
/* PipeWire callbacks                                                  */
/* ------------------------------------------------------------------ */

static void capture_process(void *userdata)
{
    (void)userdata;
    struct pw_buffer *b;

    while ((b = pw_stream_dequeue_buffer(input_stream)) != NULL) {
        struct spa_data *d = &b->buffer->datas[0];

        if (b->buffer->n_datas > 0 && d->data && d->chunk) {
            uint32_t bytes  = d->chunk->size;
            uint32_t offset = d->chunk->offset;

            if (offset <= d->maxsize && bytes <= d->maxsize - offset) {
                const float *src =
                    (const float *)((const char *)d->data + offset);
                uint32_t frames = bytes / (sizeof(float) * CHANNELS);

                int mode = atomic_load_explicit(&current_mode,
                                                memory_order_relaxed);
                uint32_t h = atomic_load_explicit(&head, memory_order_relaxed);
                uint32_t t = atomic_load_explicit(&tail, memory_order_acquire);

                for (uint32_t f = 0; f < frames; f++) {
                    if (h - t > RING_SIZE - CHANNELS)
                        break;                      /* ring full: drop rest */

                    float out[CHANNELS];
                    process_frame(mode, &src[f * CHANNELS], out);

                    for (int ch = 0; ch < CHANNELS; ch++)
                        ring[(h + ch) & RING_MASK] = out[ch];
                    h += CHANNELS;
                }
                atomic_store_explicit(&head, h, memory_order_release);
            }
        }
        pw_stream_queue_buffer(input_stream, b);
    }
}

static void playback_process(void *userdata)
{
    (void)userdata;
    struct pw_buffer *b;

    while ((b = pw_stream_dequeue_buffer(output_stream)) != NULL) {
        struct spa_data *d = &b->buffer->datas[0];

        if (b->buffer->n_datas > 0 && d->data && d->chunk) {
            uint32_t max_frames = d->maxsize / (sizeof(float) * CHANNELS);
            uint32_t frames = max_frames;
            if (b->requested && (uint32_t)b->requested < frames)
                frames = (uint32_t)b->requested;

            float *dst = (float *)d->data;
            uint32_t h = atomic_load_explicit(&head, memory_order_acquire);
            uint32_t t = atomic_load_explicit(&tail, memory_order_relaxed);

            /* Too far behind? Skip ahead (keeps frame alignment). */
            uint32_t available = h - t;
            if (available > MAX_LATENCY_SAMPLES) {
                t += (available - MAX_LATENCY_SAMPLES) & ~(uint32_t)(CHANNELS - 1);
                available = h - t;
            }

            /* Copy whole frames only so L/R never get swapped. */
            uint32_t avail_frames = available / CHANNELS;
            uint32_t copy_frames = avail_frames < frames ? avail_frames : frames;
            uint32_t count = copy_frames * CHANNELS;

            for (uint32_t i = 0; i < count; i++)
                dst[i] = ring[(t + i) & RING_MASK];

            if (frames > copy_frames)
                memset(dst + count, 0,
                       (frames - copy_frames) * CHANNELS * sizeof(float));

            atomic_store_explicit(&tail, t + count, memory_order_release);

            d->chunk->offset = 0;
            d->chunk->stride = CHANNELS * sizeof(float);
            d->chunk->size   = frames * CHANNELS * sizeof(float);
        }
        pw_stream_queue_buffer(output_stream, b);
    }
}

static const struct pw_stream_events capture_events = {
    PW_VERSION_STREAM_EVENTS,
    .process = capture_process,
};

static const struct pw_stream_events playback_events = {
    PW_VERSION_STREAM_EVENTS,
    .process = playback_process,
};

/* ------------------------------------------------------------------ */
/* Keyboard + shutdown                                                 */
/* ------------------------------------------------------------------ */

static const char *mode_name(int mode)
{
    switch (mode) {
    case MODE_RADIO:   return "Radio";
    case MODE_HELMET:  return "Helmet Comms";
    case MODE_ROBOT:   return "Robot";
    default:           return "Dry Mic";
    }
}

static void set_mode(fx_mode mode)
{
    atomic_store_explicit(&current_mode, (int)mode, memory_order_relaxed);
    printf("Mode: %s\n", mode_name(mode));
    fflush(stdout);
}

/* Terminal keys: pressing the active mode's key again goes back to dry */
static void toggle_mode(fx_mode wanted)
{
    int current = atomic_load_explicit(&current_mode, memory_order_relaxed);
    set_mode(current == (int)wanted ? MODE_DRY : wanted);
}

static void request_quit(void)
{
    printf("Quitting...\n");
    fflush(stdout);
    pw_main_loop_quit(main_loop);
}

static void *keyboard_thread(void *arg)
{
    (void)arg;
    int c;

    printf("Type D = dry, R = radio, H = helmet, B = robot, Q = quit, "
           "then Enter.\n");
    fflush(stdout);

    while ((c = getchar()) != EOF) {
        switch (c) {
        case 'd': case 'D': toggle_mode(MODE_DRY);     break;
        case 'r': case 'R': toggle_mode(MODE_RADIO);   break;
        case 'h': case 'H': toggle_mode(MODE_HELMET);  break;
        case 'b': case 'B': toggle_mode(MODE_ROBOT);   break;
        case 'q': case 'Q':
            request_quit();
            return NULL;
        default: break;
        }
    }
    return NULL;
}

/* Command pipe: lets other programs (hotkey bindings via toastfx-ctl)
 * control ToastFX. Commands are whole words, one per line. */
static char fifo_path[256];

static void init_fifo_path(void)
{
    const char *dir = getenv("XDG_RUNTIME_DIR");
    if (dir && *dir)
        snprintf(fifo_path, sizeof fifo_path, "%s/toastfx.cmd", dir);
    else
        snprintf(fifo_path, sizeof fifo_path, "/tmp/toastfx-%u.cmd",
                 (unsigned)getuid());
}

static void cleanup_fifo(void)
{
    if (fifo_path[0])
        unlink(fifo_path);
}

static void *command_thread(void *arg)
{
    (void)arg;

    /* O_RDWR keeps the pipe open between commands (no end-of-file) */
    int fd = open(fifo_path, O_RDWR);
    FILE *f = fd >= 0 ? fdopen(fd, "r") : NULL;
    if (!f) {
        perror("toastfx: command pipe");
        if (fd >= 0)
            close(fd);
        return NULL;
    }

    char line[64];
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = '\0';

        if      (!strcmp(line, "dry"))    set_mode(MODE_DRY);
        else if (!strcmp(line, "radio"))  set_mode(MODE_RADIO);
        else if (!strcmp(line, "helmet")) set_mode(MODE_HELMET);
        else if (!strcmp(line, "robot"))  set_mode(MODE_ROBOT);
        else if (!strncmp(line, "tweak ", 6)) tweak_command(line + 6);
        else if (!strcmp(line, "quit")) {
            request_quit();
            break;
        }
    }
    fclose(f);
    return NULL;
}

/* Waits for Ctrl+C / kill and asks the main loop to stop. SIGINT and SIGTERM
 * are blocked in every thread (see main), so this thread is the only one that
 * ever receives them. */
static void *signal_thread(void *arg)
{
    (void)arg;
    sigset_t set;
    int sig;

    sigemptyset(&set);
    sigaddset(&set, SIGINT);
    sigaddset(&set, SIGTERM);

    if (sigwait(&set, &sig) == 0) {
        const char *name = (sig == SIGINT) ? "SIGINT" : "SIGTERM";
        printf("\nReceived %s, shutting down...\n", name);
        fflush(stdout);
        pw_main_loop_quit(main_loop);
    }
    return NULL;
}

/* ------------------------------------------------------------------ */
/* main                                                                */
/* ------------------------------------------------------------------ */

/* Stream properties. If the environment variable `target_env` names a
 * PipeWire node, connect to that node. `strict` = wait for it instead of
 * falling back to the default device. */
static struct pw_properties *make_props(const char *category,
                                        const char *target_env, int strict)
{
    struct pw_properties *p = pw_properties_new(
        PW_KEY_MEDIA_TYPE,     "Audio",
        PW_KEY_MEDIA_CATEGORY, category,
        PW_KEY_MEDIA_ROLE,     "Communication",
        NULL);

    const char *target = p ? getenv(target_env) : NULL;
    if (target && *target) {
        pw_properties_set(p, PW_KEY_TARGET_OBJECT, target);
        if (strict)
            pw_properties_set(p, "node.dont-fallback", "true");
    }
    return p;
}

int main(int argc, char **argv)
{
    /* Work out where the hotkey command pipe lives before anything can
     * fail and try to clean it up. */
    init_fifo_path();
    helmet_init();
    radio_init();

    /* Block SIGINT/SIGTERM first so every thread created later (PipeWire's
     * own included) inherits the block; signal_thread picks them up. */
    sigset_t sigs;
    sigemptyset(&sigs);
    sigaddset(&sigs, SIGINT);
    sigaddset(&sigs, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &sigs, NULL);

    pw_init(&argc, &argv);

    struct pw_main_loop *loop = pw_main_loop_new(NULL);
    if (!loop) {
        fprintf(stderr, "Could not create PipeWire main loop\n");
        pw_deinit();
        return 1;
    }

    main_loop = loop;
    struct pw_loop *l = pw_main_loop_get_loop(loop);

    /* Clean exit on Ctrl+C / kill */
    pthread_t sig_thread;
    if (pthread_create(&sig_thread, NULL, signal_thread, NULL) == 0)
        pthread_detach(sig_thread);
    else
        fprintf(stderr, "Warning: Ctrl+C handler not available\n");

    input_stream = pw_stream_new_simple(
        l, "ToastFX Microphone",
        make_props("Capture", "TOASTFX_INPUT", 0),
        &capture_events, NULL);

    output_stream = pw_stream_new_simple(
        l, "ToastFX Passthrough",
        make_props("Playback", "TOASTFX_OUTPUT", 1),
        &playback_events, NULL);

    if (!input_stream || !output_stream) {
        fprintf(stderr, "Could not create audio streams\n");
        goto cleanup;
    }

    struct spa_audio_info_raw audio = {
        .format   = SPA_AUDIO_FORMAT_F32,
        .rate     = SAMPLE_RATE,
        .channels = CHANNELS,
        .position = { SPA_AUDIO_CHANNEL_FL, SPA_AUDIO_CHANNEL_FR },
    };

    uint8_t storage[1024];
    struct spa_pod_builder builder =
        SPA_POD_BUILDER_INIT(storage, sizeof(storage));
    const struct spa_pod *params[1];
    params[0] = spa_format_audio_raw_build(&builder, SPA_PARAM_EnumFormat, &audio);

    const enum pw_stream_flags flags = PW_STREAM_FLAG_AUTOCONNECT |
                                       PW_STREAM_FLAG_MAP_BUFFERS |
                                       PW_STREAM_FLAG_RT_PROCESS;

    int in_result  = pw_stream_connect(input_stream,  PW_DIRECTION_INPUT,
                                       PW_ID_ANY, flags, params, 1);
    int out_result = pw_stream_connect(output_stream, PW_DIRECTION_OUTPUT,
                                       PW_ID_ANY, flags, params, 1);
    if (in_result < 0 || out_result < 0) {
        fprintf(stderr, "Could not connect audio streams\n");
        goto cleanup;
    }

    /* Command pipe, for hotkeys via toastfx-ctl */
    cleanup_fifo();                          /* clear a stale one */
    pthread_t command;
    if (mkfifo(fifo_path, 0600) == 0 &&
        pthread_create(&command, NULL, command_thread, NULL) == 0)
        pthread_detach(command);
    else
        fprintf(stderr, "Warning: hotkey command pipe not available\n");

    /* Typing commands only makes sense when run from a terminal */
    if (isatty(STDIN_FILENO)) {
        pthread_t keyboard;
        if (pthread_create(&keyboard, NULL, keyboard_thread, NULL) == 0)
            pthread_detach(keyboard);
        else
            fprintf(stderr, "Warning: keyboard thread not available\n");
    }

    printf("ToastFX running (mode: %s). Press Ctrl+C to stop.\n",
           mode_name(atomic_load(&current_mode)));
    fflush(stdout);
    pw_main_loop_run(loop);

    cleanup_fifo();
    pw_stream_destroy(input_stream);
    pw_stream_destroy(output_stream);
    pw_main_loop_destroy(loop);
    pw_deinit();
    /* command_thread sits in fgets() holding its FILE's stdio lock, so a normal
     * return would deadlock in exit() flushing that FILE. Everything is already
     * cleaned up, so leave directly. */
    fflush(stdout);
    _exit(0);

cleanup:
    cleanup_fifo();
    if (input_stream)  pw_stream_destroy(input_stream);
    if (output_stream) pw_stream_destroy(output_stream);
    pw_main_loop_destroy(loop);
    pw_deinit();
    return 1;
}