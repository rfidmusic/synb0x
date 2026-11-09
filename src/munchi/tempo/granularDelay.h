#pragma once
#include "daisysp.h"
#include "clockManager.h"
#include "SimpleCrossfade.h"
#include "temp_led_stuff.h" // Munchi: color_xfade came in via ui.h on CHOMPI
#include "../munchi_port.h" // Blackbox: 16-bit buffers, munchi_rand, munchi_sinf

constexpr float delayDivs[9] = {1.f/8.f, 1.f/6.f, 1.f/4.f, 1.f/3.f, 3.f/8.f, 1.f/2.f, 3.f/4.f, 1.f, 2.f};
constexpr size_t frozenDelayIntervals[9] = {6, 8, 12, 16, 18, 24, 36, 48, 96};
constexpr uint8_t kMaxGrains = 12;
constexpr uint32_t kMaxCrossfadeSamps = 256;
constexpr uint32_t kMaxEventCrossfadeSamps = 1024;
constexpr size_t kMaxFonepoleSamps = 4605;

constexpr float delayLeftColors[9][3] = {{0.f, 1.f, 0.f}, {1.f, 0.f, 0.f}, {.2f, 1.f, .2f}, {1.f, .3f, .1f}, {.4f, 1.f, .4f}, {1.f, .75f, .1f}, {.6f, 1.f, .6f}, {1.f, 1.f, .3f}, {.8f, 1.f, .8f}};
constexpr float delayRightColors[9][3] = {{0.f, 0.f, 1.f}, {1.f, .6f, .24f}, {.2f, .2f, 1.f}, {1.f, .7f, .44f}, {.4f, .4f, 1.f}, {1.f, .8f, .64f}, {.6f, .6f, 1.f}, {1.f, .9f, .84f}, {.8f, .8f, 1.f}};

constexpr float delayStereoOffsetLeft = 960.f;
constexpr float delayStereoOffsetRight = 480.f;

namespace chompi {
    inline void getSample(const mbuf_t *buffer, float read_head, float *out_l, float *out_r, size_t buffer_size) {
        float spread = MUNCHI_SPREAD; // Blackbox: the Width setting scales TEMPO's offsets
        float right_read_head = read_head - delayStereoOffsetRight * spread;
        if (right_read_head < 0.f) {
            right_read_head += static_cast<float>(buffer_size);
        }
        float left_read_head = read_head - delayStereoOffsetLeft * spread;
        if (left_read_head < 0.f) {
            left_read_head += static_cast<float>(buffer_size);
        }

        size_t i0_l = static_cast<int>(left_read_head);
        if (i0_l >= buffer_size) {
            i0_l -= buffer_size;
        }
        size_t i1_l = (i0_l + 1);
        if (i1_l >= buffer_size) {
            i1_l -= buffer_size;
        }

        size_t i0_r = static_cast<int>(right_read_head);
        if (i0_r >= buffer_size) {
            i0_r -= buffer_size;
        }
        size_t i1_r = (i0_r + 1);
        if (i1_r >= buffer_size) {
            i1_r -= buffer_size;
        }

        float frac = left_read_head - static_cast<float>(i0_l);

        // Read interleaved stereo
        float a_l = mbuf_load(buffer[i0_l * 2]);
        float b_l = mbuf_load(buffer[i1_l * 2]);

        float a_r = mbuf_load(buffer[i0_r * 2 + 1]);
        float b_r = mbuf_load(buffer[i1_r * 2 + 1]);

        *out_l += (a_l + frac * (b_l - a_l));
        *out_r += (a_r + frac * (b_r - a_r));
    }

    inline float fast_rsqrt(float x) {
        union { float f; uint32_t i; } conv;
        conv.f = x;
        conv.i = 0x5f3759dfU - (conv.i >> 1);
        float y = conv.f;
        // one Newton step to improve accuracy
        y = y * (1.5f - 0.5f * x * y * y);
        return y;
    }

    inline float fast_sqrt(float x) {
        if (x <= 0.f) return 0.f;
        return x * fast_rsqrt(x); // sqrt(x) ≈ x * (1/sqrt(x))
    }

    // Blackbox: no RAM for a table; nothing in the delay reads it
    inline void InitHalfSineTable() {}

};

class delayVoice {
    public:
    delayVoice() {};
    ~delayVoice() {};

    enum delayEvent {
        RETRIG,
        REVERSE,
        PITCH_UP,
        PITCH_DOWN,
        NONE
    };

    void Init(mbuf_t *buffer, size_t buffer_size) {
        buffer_ = buffer;
        buffer_size_ = buffer_size;
        crossfade_env_ = 1.f;
        curEvent = nextEvent = NONE;
        curPan = nextPan = 0.f;
        div_pos_ = 8;
    }

    void updateTempo(float delay_samples, uint32_t write_head) {
        if (!div_crossfade_) {
            delay_samples_ = delay_samples;
        }
        write_head_ = write_head;
    }

    void startFadeIn() {
        if (fading_in_ || fading_out_ || active_) {
            return;
        }
        active_ = true;
        fading_in_ = true;
        event_crossfade_counter_ = 0;
        curEvent = nextEvent;
        nextEvent = NONE; // Until otherwise changed
        curPan = nextPan;
        nextPan = 0.f;
        if (curEvent == delayEvent::PITCH_UP && div_pos_ < 5) {

            // Blackbox: never reach back further than the buffer holds (4 s here, 10 s on TEMPO)
            read_head_ = write_head_ - fminf(delay_samples_ * (0.5f / delayDivs[div_pos_]), .85f * static_cast<float>(buffer_size_));
        }
        else {
            read_head_ = write_head_ - delay_samples_;
        }
        if (read_head_ < 0.f) {
            read_head_ += static_cast<float>(buffer_size_);
        }
    }

    void startFadeOut() {
        if (fading_in_ || fading_out_ || !active_) {
            return;
        }
        fading_out_ = true;
        event_crossfade_counter_ = kMaxEventCrossfadeSamps;
    }

    void setNextEvent(size_t event, float pan) {
        nextEvent = static_cast<delayEvent>(event);
        nextPan = pan;
    }

    bool setDivCrossfade(float new_read_head, float new_delay_samples, size_t new_div) {
        if (active_) {
            if (div_crossfade_) {
                return false;
            }
            div_read_head_ = new_read_head;
            div_delay_samples_ = new_delay_samples;
            div_crossfade_counter_ = kMaxCrossfadeSamps;
            div_crossfade_ = true;
        }
        else {
            read_head_ = new_read_head;
        }
        div_pos_ = new_div;
        return true;
    }

    void Read(float *out_l, float *out_r) {

        if (!active_) {
            *out_l += 0.f;
            *out_r += 0.f;
            return;
        }

        crossfade_env_ = 1.f;
        div_env_ = 1.f;

        float panL = chompi::fast_sqrt(0.5f * (1.f - curPan));
        float panR = chompi::fast_sqrt(0.5f * (1.f + curPan));

        if (fading_in_) {
            event_crossfade_counter_++;
            if (event_crossfade_counter_ > kMaxEventCrossfadeSamps) {
                event_crossfade_counter_ = kMaxEventCrossfadeSamps;
                fading_in_ = false;
            }
            float phase = static_cast<float>(event_crossfade_counter_) / static_cast<float>(kMaxEventCrossfadeSamps);
            crossfade_env_ = munchi_sinf(phase * PI_F * 0.5f);
        }
        else if (fading_out_) {
            event_crossfade_counter_--;
            if (event_crossfade_counter_ < 1) {
                fading_out_ = false;
                active_ = false;
            }
            float phase = static_cast<float>(event_crossfade_counter_) / static_cast<float>(kMaxEventCrossfadeSamps);
            crossfade_env_ = munchi_sinf(phase * PI_F * 0.5f);
        }

        switch (curEvent) {
            case NONE: {
                read_head_ = write_head_ - delay_samples_;
            }
            break;
            case RETRIG: {
                read_head_ = static_cast<float>(write_head_) - fminf(delay_samples_ * 1.125f, .85f * static_cast<float>(buffer_size_)); // Blackbox: clamped to the buffer
            }
            break;
            case REVERSE: {
                read_head_ -= 1.f;
            }
            break;
            case PITCH_UP: {
                read_head_ += 2.f;
            }
            break;
            case PITCH_DOWN: {
                read_head_ += .5f;
            }
            break;
        };
        if (read_head_ < 0.f) {
            read_head_ += static_cast<float>(buffer_size_);
        }
        if (read_head_ >= static_cast<float>(buffer_size_)) {
            read_head_ -= static_cast<float>(buffer_size_);
        }

        float sig_l = 0.f;
        float sig_r = 0.f;

        if (div_crossfade_) {
            div_crossfade_counter_--;
            div_env_ = static_cast<float>(div_crossfade_counter_) / static_cast<float>(kMaxCrossfadeSamps);
            if (div_crossfade_counter_ == 0) {
                read_head_ = div_read_head_;
                delay_samples_ = div_delay_samples_;
                div_crossfade_ = false;
                div_env_ = 1.f;
            }
        }

        chompi::getSample(buffer_, read_head_, &sig_l, &sig_r, buffer_size_);
        *out_l += sig_l * crossfade_env_ * div_env_ * panL;
        *out_r += sig_r * crossfade_env_ * div_env_ * panR;

        if (div_crossfade_) {

            switch (curEvent) {
                case NONE: {
                    div_read_head_ += 1.f;
                }
                break;
                case RETRIG: {
                    div_read_head_ += 1.f;
                }
                break;
                case REVERSE: {
                    div_read_head_ -= 1.f;
                }
                break;
                case PITCH_UP: {
                    div_read_head_ += 2.f;
                }
                break;
                case PITCH_DOWN: {
                    div_read_head_ += .5f;
                }
                break;
            }
            if (div_read_head_ < 0.f) {
                div_read_head_ += static_cast<float>(buffer_size_);
            }
            if (div_read_head_ >= static_cast<float>(buffer_size_)) {
                div_read_head_ -= static_cast<float>(buffer_size_);
            }

            float c_sig_l = 0.f;
            float c_sig_r = 0.f;
            chompi::getSample(buffer_, div_read_head_, &c_sig_l, &c_sig_r, buffer_size_);
            *out_l += c_sig_l * crossfade_env_ * (1.f - div_env_) * panL;
            *out_r += c_sig_r * crossfade_env_ * (1.f - div_env_) * panR;
        }
    }

    mbuf_t *buffer_;
    size_t buffer_size_;
    uint32_t write_head_;
    
    float read_head_;
    float crossfade_env_;
    float delay_samples_;
    delayEvent curEvent, nextEvent;
    float curPan, nextPan;
    uint32_t event_crossfade_counter_;
    bool active_;
    bool fading_in_, fading_out_;
    size_t div_pos_;

    float div_read_head_, div_delay_samples_;
    bool div_crossfade_;
    size_t div_crossfade_counter_;
    float div_env_;
};

class granularDelay {
    public:
    granularDelay() {};
    ~granularDelay() {};

    enum delayEvent {
        RETRIG,
        REVERSE,
        PITCH_UP,
        PITCH_DOWN,
        NONE
    };

    void Init(mbuf_t *buff, mbuf_t *frozen_buff, size_t delaySize, clockManager *clock_manager, bool mute_option) {
        buffer_ = buff;
        frozen_buffer_ = frozen_buff;
        buffer_size_ = delaySize;

        clock_manager_ = clock_manager;
        delay_mute_option_ = mute_option;

        write_head_ = 0;
        delay_samples_ = delay_samples_target_ = 72000.f;

        knob_position_ = .5f;
        alt_control_ = 0.f;
        delay_div_position_ = 8;

        setFeedback(.3f);

        bufferWrapXfade.Init(kMaxCrossfadeSamps);
        bufferToggleXfade.Init(kMaxCrossfadeSamps);
        bufferClearDownXfade.Init(kMaxCrossfadeSamps);
        bufferClearUpXfade.Init(kMaxCrossfadeSamps);

        wet_amt_ = wet_amt_target_ = 0.f;

        curIdx = 0;
        nextIdx = 1;
        myVoices[curIdx].active_ = true;

        for (size_t i = 0; i < 2; ++i) {
            myVoices[i].Init(buffer_, buffer_size_);
        }

        chompi::InitHalfSineTable();
    }

    void write(float in_l, float in_r) {
        if (lock_buffer_) {
            return;
        }
        size_t idx = write_head_ * 2;
        buffer_[idx] = mbuf_store((in_l + cur_sig_l_) * lockEnv);
        buffer_[idx + 1] = mbuf_store((in_r + cur_sig_r_) * lockEnv);

        write_head_ = write_head_ + 1 >= buffer_size_ ? 0 : write_head_ + 1;   // Synb0x: no division per sample
    }

    void read(float* out_l, float* out_r)
    {
        lockEnv = 1.f;
        muteEnv = 1.f;

        if (mute_) {
            if (bufferClearDownXfade.isRunning()) {
                bool done = false; // Munchi: the firmware passed nullptr here, and
                // TO_ZERO writes it at the end of the fade -- a store to
                // address 0, harmless on the CHOMPI's flash, a crash here
                bufferClearDownXfade.Process(&muteEnv, nullptr, &done);
            }
            else if (!bufferClearUpXfade.isRunning()) {
                muteEnv = 0.f;
                mute_counter_++;
                if (mute_counter_ >= mute_end_) {
                    bufferClearUpXfade.startFade(Crossfade::CrossfadeType::TO_ONE);
                }
            }
            else {
                bool crossed = false;
                bufferClearUpXfade.Process(&muteEnv, nullptr, &crossed);
                if (crossed) {
                    mute_ = false;
                }
            }
        }

        if (delay_on_) {
            processDelay(out_l, out_r);
            *out_l *= muteEnv;
            *out_r *= muteEnv;
        }
        else {
            *out_l = *out_r = 0.f;
        }
    }

    void processDelay(float* out_l, float* out_r) {

        fonepole(wet_amt_, wet_amt_target_, .001f);

        *out_l = *out_r = 0.f; // Need to fix this

        float crossfadeEnv = 1.f;
        float divEnv = 1.f;

        size_t t_ = clock_manager_->getTempo();
        size_t t_us = clock_manager_->getInterval();
        size_t new_interval = 8;
        if (knob_position_ < .4f) {
            new_interval = static_cast<size_t>(knob_position_ * 20.0f + 0.5f); // 0–0.4 maps to 0–8
        }
        if (knob_position_ > .6f) {
            new_interval = static_cast<size_t>((1.0f - knob_position_) * 20.0f + 0.5f);
        }

        if (new_interval != delay_div_position_) {
            if (lock_buffer_) {
                float samples_per_tick = (48000.f * 60.f) / (t_ * 12.f);
                float phase_offset = frozen_read_head_ - static_cast<float>(clock_pulse_counter_[delay_div_position_]) * samples_per_tick;
                crossfade_read_head_ = static_cast<float>(clock_pulse_counter_[new_interval]) * samples_per_tick + phase_offset;
                div_crossfade_ = true;
                div_counter_ = kMaxCrossfadeSamps;
                delay_div_position_ = new_interval;
            }
            else {
                float new_delay_samps = fminf((60000.f / t_) * 4.f * delayDivs[new_interval] * 48.f, .75f * static_cast<float>(buffer_size_)); // Blackbox: clamped
                float new_read_head = write_head_ - new_delay_samps;
                if (new_read_head < 0.f) {
                    new_read_head += static_cast<float>(buffer_size_);
                }
                bool success = true;
                for (size_t i = 0; i < 2; ++i) {
                    if (!myVoices[i].setDivCrossfade(new_read_head, new_delay_samps, new_interval)) {
                        success = false;
                    }
                }
                if (success) {
                    delay_samples_ = new_delay_samps;
                    delay_div_position_ = new_interval;
                }
            }
        }

        delay_samples_target_ = fminf(static_cast<float>(t_us) * .192f * delayDivs[delay_div_position_], .75f * static_cast<float>(buffer_size_)); // Blackbox: clamped
        fonepole(delay_samples_, delay_samples_target_, .001f);

        if (bufferToggleXfade.isRunning()) {
            bool crossed = false;
            bufferToggleXfade.Process(&lockEnv, nullptr, &crossed);
            if (crossed) {
                lock_buffer_ = !lock_buffer_;
                if (lock_buffer_) {
                    frozen_read_head_ = frozen_write_head - delay_samples_;
                    if (frozen_read_head_ < 0.f) {
                        frozen_read_head_ += static_cast<float>(buffer_size_);
                    }
                    frozen_sample_counter_ = 0;
                    for (size_t i = 0; i < 9; ++i) {
                        clock_pulse_counter_[i] = 0;
                    }
                }
            }
        }

        if (lock_buffer_) {

            float read_end_ = static_cast<float>(frozen_write_head) - delay_samples_;
            if(read_end_ < 0.f) {
                read_end_ += buffer_size_;
            }

            frozen_read_head_+= 1.f;

            for (size_t i = 0; i < 9; ++i) {
                if (clock_pulse_counter_[i] >= frozenDelayIntervals[i]) {
                    clock_pulse_counter_[i] = 0;
                    if (i == delay_div_position_) {
                        bufferWrapXfade.startFade(Crossfade::CrossfadeType::THROUGH_ZERO);
                    }
                }
            }

            frozen_sample_counter_++;

            if (div_crossfade_) {
                divEnv = static_cast<float>(div_counter_) / static_cast<float>(kMaxCrossfadeSamps);
            }
            if (bufferWrapXfade.isRunning()) {
                bool crossed = false;
                bufferWrapXfade.Process(&crossfadeEnv, nullptr, &crossed);
                if (crossed) {
                    frozen_read_head_ = read_end_;
                    frozen_sample_counter_ = 0;
                }
            }

            if (frozen_read_head_ < 0.f) {
                frozen_read_head_ += static_cast<float>(buffer_size_);
            }
            if (frozen_read_head_ >= static_cast<float>(buffer_size_)) {
                frozen_read_head_ -= static_cast<float>(buffer_size_);
            }

            float sig_l = 0.f;
            float sig_r = 0.f;
            chompi::getSample(frozen_buffer_, frozen_read_head_, &sig_l, &sig_r, buffer_size_);
            *out_l = sig_l * crossfadeEnv * wet_amt_ * divEnv * lockEnv;
            *out_r = sig_r * crossfadeEnv * wet_amt_ * divEnv * lockEnv;

            if (div_crossfade_) {
                float c_sig_l = 0.f;
                float c_sig_r = 0.f;
                chompi::getSample(frozen_buffer_, crossfade_read_head_, &c_sig_l, &c_sig_r, buffer_size_);

                *out_l += c_sig_l * crossfadeEnv * wet_amt_ * (1.f - divEnv) * lockEnv;
                *out_r += c_sig_r * crossfadeEnv * wet_amt_ * (1.f - divEnv) * lockEnv;

                div_counter_--;
                if (div_counter_ == 0) {
                    frozen_read_head_ = crossfade_read_head_;
                    div_crossfade_ = false;
                }
                crossfade_read_head_ += 1.f;
                if (crossfade_read_head_ > static_cast<float>(buffer_size_)) {
                    crossfade_read_head_ -= static_cast<float>(buffer_size_);
                }
            }

            cur_sig_l_ = 0.f;
            cur_sig_r_ = 0.f;

        }
        else {
            for (size_t i = 0; i < 2; ++i) {
                myVoices[i].updateTempo(delay_samples_, write_head_);
            }
            size_t div = clock_manager_->getClockDivPos(0);
            float clock_mult = 1.f;
            clock_interval_ = 1;
            if (div > 2){
                clock_interval_ = 2;
                clock_mult = 2.f;
            }

            if (clock_edge_) {
                clock_counter_++;
                if (clock_counter_ >= clock_interval_) {
                    event_type_[0] = event_type_[1];
                    bool random_event = static_cast<float>(munchi_rand()) / static_cast<float>(MUNCHI_RAND_MAX) < (0.5f * alt_control_);
                    if (random_event) {
                        curIdx = nextIdx;
                        nextIdx = (curIdx + 1) % 2;
                        float pan = 0.f;
                        if (knob_position_ < .5f) {
                            event_type_[1] = static_cast<delayEvent>(munchi_rand() % 4);
                        }
                        else {
                            event_type_[1] = delayEvent::PITCH_UP;
                            pan = randomPan();
                        }
                        myVoices[curIdx].setNextEvent(event_type_[1], pan);
                    }
                    else {
                        event_type_[1] = delayEvent::NONE;
                        if (event_type_[0] != NONE) {
                            curIdx = nextIdx;
                            nextIdx = (curIdx + 1) % 2;
                            myVoices[curIdx].setNextEvent(4, 0.f);
                        }
                    }
                    clock_counter_ = 0;
                }
                clock_edge_ = false;
            }

            if (event_type_[0] != NONE || event_type_[1] != NONE) {
                myVoices[curIdx].startFadeIn(); // They manage themselves
                myVoices[nextIdx].startFadeOut();
            }

            // Read interleaved stereo
            for (size_t i = 0; i < 2; ++i) {
                myVoices[i].Read(out_l, out_r);
            }

            *out_r *= wet_amt_ * lockEnv;
            *out_l *= wet_amt_ * lockEnv;

            cur_sig_l_ = *out_l * delay_feedback_amt_;
            cur_sig_r_ = *out_r * delay_feedback_amt_;

            size_t idx = frozen_write_head * 2;
            frozen_buffer_[idx] = mbuf_store(*out_l);
            frozen_buffer_[idx + 1] = mbuf_store(*out_r);
            frozen_write_head = frozen_write_head + 1 >= buffer_size_ ? 0 : frozen_write_head + 1;   // Synb0x: (as above)
        }
    }

    float randomPan() {
        float effective_range = 0.5f + (alt_control_ * 0.5f); // Range: [0.5, 1.0]
        float r = ((int)(munchi_rand() % 2001) - 1000) / 1000.f; // [-1.0, 1.0]
        return r * effective_range;
    }

    void setFeedback(float val) {
        delay_feedback_amt_ = val * .975f;
    }

    void setMainControl(float val) {
        if (val < .45f) {
            // random delay
            if (val < .45 && val > .4) {
                wet_amt_target_ = 9.f - val * 20.f; // .45 to .4 mapped to 0 to 1
            }
            else {
                wet_amt_target_ = 1.f;
            }
            delay_on_ = true;
        }
        else if (val > .55) {
            // reverb delay
            if (val < .6 && val > .55) {
                wet_amt_target_ = val * 20.f - 11.f;
            }
            else {
                wet_amt_target_ = 1.f;
            }
            delay_on_ = true;
        }
        else {
            wet_amt_target_ = 0.f;
            if (wet_amt_ < .01f) {
                delay_on_ = false;
            }
        }
        knob_position_ = val;
    }

    /** Munchi: options.json changes apply without a restart */
    void setMuteOption(bool m) { delay_mute_option_ = m; }
    bool getBufferLock() const { return lock_buffer_; }
    bool getDelayOn() const { return delay_on_; }

    void setAltControl(float val) {
        alt_control_ = val;
    }

    void toggleBufferLock() {
        if (delay_on_) {
            bufferToggleXfade.startFade(Crossfade::CrossfadeType::THROUGH_ZERO);
        }
        if (lock_buffer_ && delay_mute_option_) {
            setMute();
        }
    }

    void setBufferLock(bool t) {
        lock_buffer_ = t;
        if (!t && delay_mute_option_) {
            setMute();
        }
    }

    void setMute() {
        mute_ = true;
        mute_end_ = delay_samples_;
        mute_counter_ = 0;
        bufferClearDownXfade.startFade(Crossfade::CrossfadeType::TO_ZERO);
    }

    void getColors(float *colors) {
        float lock_pos = 1.f;
        if (knob_position_ > .5f) {
            if (lock_buffer_ && knob_position_ > .55f) {
                lock_pos = static_cast<float>(frozen_sample_counter_) / delay_samples_;
                lock_pos = fclamp(lock_pos, 0.f, 1.f);
            }
            if (knob_position_ < .6f) {
                float idx = (knob_position_ - .5f) * 10.f;
                colors[0] = color_xfade(.14f, delayRightColors[8][0], idx) * lock_pos;
                colors[1] = color_xfade(1.f, delayRightColors[8][1], idx) * lock_pos;
                colors[2] = color_xfade(.92f, delayRightColors[8][2], idx) * lock_pos;
            }
            else {
                colors[0] = delayRightColors[delay_div_position_][0] * lock_pos;
                colors[1] = delayRightColors[delay_div_position_][1] * lock_pos;
                colors[2] = delayRightColors[delay_div_position_][2] * lock_pos;
            }
        }
        else {
            if (lock_buffer_ && knob_position_ < .45) {
                lock_pos = static_cast<float>(frozen_sample_counter_) / delay_samples_;
                lock_pos = fclamp(lock_pos, 0.f, 1.f);
            }
            if (knob_position_ > .4f) {
                float idx = (.5f - knob_position_) * 10.f;
                colors[0] = color_xfade(.14f, delayLeftColors[8][0], idx) * lock_pos;
                colors[1] = color_xfade(1.f, delayLeftColors[8][1], idx) * lock_pos;
                colors[2] = color_xfade(.92f, delayLeftColors[8][2], idx) * lock_pos;
            }
            else {
                colors[0] = delayLeftColors[delay_div_position_][0] * lock_pos;
                colors[1] = delayLeftColors[delay_div_position_][1] * lock_pos;
                colors[2] = delayLeftColors[delay_div_position_][2] * lock_pos;
            }
        }
    }

    void setClockEdge() {
        clock_edge_ = true;
    }

    void setClockPulse() {
        if (!lock_buffer_) {
            return;
        }
        for (size_t i = 0; i < 9; ++i) {
            clock_pulse_counter_[i]++;
        }
    }

    delayVoice myVoices[2];

    private:
    mbuf_t *buffer_;
    uint32_t write_head_;
    uint32_t buffer_size_;
    float delay_samples_, delay_samples_target_;
    float cur_sig_l_, cur_sig_r_;

    mbuf_t *frozen_buffer_;
    uint32_t frozen_write_head;
    float frozen_read_head_;
    size_t frozen_sample_counter_;
    size_t clock_pulse_counter_[9];
    size_t curDiv_;

    bool div_crossfade_;
    float crossfade_read_head_;
    float div_counter_;

    Crossfade bufferWrapXfade;
    Crossfade bufferToggleXfade;
    Crossfade bufferClearDownXfade;
    Crossfade bufferClearUpXfade;
    float lockEnv;

    float wet_amt_, wet_amt_target_;
    bool delay_on_;
    bool lock_buffer_;
    float delay_feedback_amt_;

    float knob_position_;
    float alt_control_;
    size_t delay_div_position_;

    clockManager *clock_manager_;

    bool mute_;
    size_t mute_counter_, mute_end_;
    float muteEnv;
    size_t mute_wait_;
    bool delay_mute_option_;

    bool clock_edge_;
    delayEvent event_type_[2] = {NONE, NONE};
    uint8_t curIdx, nextIdx;
    uint8_t clock_counter_, clock_interval_;
};