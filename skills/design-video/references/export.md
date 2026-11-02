# design-video — delivery spec

## Delivery

| Setting | Value |
|---|---|
| Container | MP4 |
| Video | H.264 (High profile), 1920 × 1080, 30 fps **constant**, `yuv420p` |
| Colour | sRGB source, converted and tagged BT.709, limited range |
| Quality | CRF 18 (fine text needs it); 4K by rendering at scale 2 |
| Audio | AAC, 48 kHz, 192 kbit/s |
| Loudness | −14 LUFS integrated, true peak −1 dBTP |
| Fast start | on (index at the front so it plays while loading) |
| Captions | burned in by the composition; also deliver an `.srt` |
| File names | `<topic>-<yyyy-mm-dd>-v<version>-<theme>.mp4` |

`scripts/render.mjs` produces exactly this (see `render.md`). **Verified** on a 5-second clip:
150 frames at 30 fps, 1920 × 1080, `h264 (High)`, `yuv420p(tv, bt709)`, AAC 48 kHz, and a
−14.0 LUFS reading after the loudness filter.

## Loudness

The renderer applies a single-pass `loudnorm` (`I=-14:TP=-1:LRA=11`) when you pass `--audio`. That
is enough for speech over music. For a final master, measure first and feed the measured values
back in (two-pass):

```bash
ffmpeg -i audio.wav -af loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null -
# then run loudnorm again with measured_I, measured_TP, measured_LRA, measured_thresh from the output
```

## Checking an MP4

The renderer installs a static `ffmpeg` in its work folder (`<work>/node_modules/@ffmpeg-installer/*/ffmpeg`).
With any `ffmpeg`:

```bash
ffmpeg -i out.mp4 2>&1 | grep -E "Duration|Stream"          # codec, size, fps, pixel format, audio
ffmpeg -i out.mp4 -map 0:v -f null - 2>&1 | grep -oE "frame= *[0-9]+" | tail -1   # frame count
ffmpeg -i out.mp4 -af ebur128=peak=true -f null - 2>&1 | grep -E "I:|Peak:" | tail -2   # loudness
```

Expect `frame = duration × 30`, `1920x1080`, `30 fps`, `yuv420p`, and `I: -14.0 LUFS`.

## Pre-release checklist

- [ ] The probe above shows 1920 × 1080, 30 fps, `yuv420p`, `h264`, AAC when there is audio.
- [ ] Frame count equals duration × fps.
- [ ] Watched once at full size with sound, once on a phone muted (captions carry it).
- [ ] No frame has text outside the safe areas or under 40 px.
- [ ] Loudness measured at −14 LUFS, peak at or under −1 dBTP.
- [ ] `.srt` text matches the voice-over word for word.
- [ ] File names follow the pattern; the storyboard and the composition source are saved next to the video.
- [ ] A loop's last frame leads straight back into its first: render stills at `t = 0` and at `t = duration - 1/fps` and check the motion between them is one frame step.
