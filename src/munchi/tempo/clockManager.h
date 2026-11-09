/* clockManager.h -- the three questions TEMPO's granularDelay asks of its
 * clock (tempo/upstream has the firmware's 362-line original), answered from
 * the host's tempo.
 *
 * TEMPO's "tempo" is twice the BPM (its timer ran at tempo * 12 / 60 Hz,
 * i.e. 24 pulses per quarter note of tempo / 2), and getInterval() is one
 * period of that tempo in microseconds. The division position only decides
 * whether random delay events come every step or every other step (> 2:
 * every other); 2 is TEMPO's x1. */
#pragma once
#include <stddef.h>

class clockManager
{
  public:
    void   setBpm(float bpm) {
        bpm_ = bpm < 20.f ? 20.f : bpm > 400.f ? 400.f : bpm;
        interval_ = (size_t)(60000000.f / (bpm_ * 2.f));   /* Synb0x: once per tempo change, not every sample */
    }
    float  bpm() const { return bpm_; }
    size_t getTempo() const { return (size_t)(bpm_ * 2.f + .5f); }
    size_t getInterval() const { return interval_; }
    int    getClockDivPos(size_t) const { return div_pos_; }
    void   setDivPos(int p) { div_pos_ = p; }

  private:
    float bpm_     = 120.f;
    size_t interval_ = (size_t)(60000000.f / (120.f * 2.f));
    int   div_pos_ = 2;
};
