# ticksonic | A Time and Sales CLI with Sound and Color

A Python command-line interface (CLI) that displays stock transactions (time and sales) above a user-defined value threshold. Transactions are printed showing the color-coded **dollar value** of each transaction along with sounds that depend on their position relative to the bid and ask. 

## Introduction

This program can be used by active traders or market enthusiasts who want a quick, intuitive view of significant transactions happening in real time. Instead of listing timestamp, price, and ticker for each transaction, it prints the **dollar value** of the trade. The program also uses a color scheme to indicate whether trades occur above the ask, at the ask, between the ask and bid, at the bid, or below the bid—and can play different sounds for each scenario.

## Prerequisites

1. **Python 3.x** installed on your system.
2. A **Polygon.io** account to obtain your `POLYGON_API_KEY`.
3. A `.env` file containing a valid `POLYGON_API_KEY` in the same directory as the script.

   ```
   POLYGON_API_KEY=your_polygon_api_key_here
   ```

## Setup and Installation

1. **Install poetry** (if not already installed):
   The recommended way to install Poetry on Ubuntu (including 22.04) is via the official installation script. You can run:

    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```

    After the installation completes, make sure you add Poetry to your `PATH`. By default, Poetry is installed under `~/.local/bin`:

    ```bash
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    source ~/.bashrc
    ```

    Finally, verify that Poetry is correctly installed:

    ```bash
    poetry --version
    ```

    That’s it! Now you can use Poetry to manage your Python projects.
   
2. Ensure you have placed your `POLYGON_API_KEY` in the `.env` file.
   
3. **Install the dependencies** (only needed once, or whenever you update `pyproject.toml`):
   ```bash
   poetry install
   ```
   This will read the dependencies listed in `pyproject.toml` (and potentially `poetry.lock`) and install them into the Poetry-managed virtual environment.

4. **Run your script**:
   ```bash
   poetry run python ticksonic.py nvda 10000 100000
   ```
   Here:
   - `nvda` is the **stock ticker** (e.g., NVDA for NVIDIA).
   - `10000` is the **threshold (in dollars)** above which trades will be displayed.
   - `100000` is the **“big threshold” (in dollars)** for highlighting very large trades with bolder color/pitch changes.

If you *already* ran `poetry install` sometime earlier (and nothing changed in `pyproject.toml`), you should be able to directly run the script using the same `poetry run ...` command without reinstalling. 

## Usage

1. When the script is running, it will:
   - Only display transactions above the configured threshold.
   - Print the dollar value of each transaction.
   - Use different colors and play sounds to indicate transactions that occur:
     - **Above the ask**
     - **At the ask**
     - **Between the ask and the bid**
     - **At the bid**
     - **Below the bid**

2. **Color Legend**:

   - **Yellow**: Trade executed **above** the ask  
   - **Green**: Trade executed **at** the ask  
   - **White**: Trade executed **between** the bid and the ask
   - **Red**: Trade executed **at** the bid  
   - **Magenta**: Trade executed **below** the bid  

3. **Sound Legend**

   - The **cash register sound** is for lifting above the ask (yellow color)
   - Lifting the ask is "**Buy!**" (Green)
   - The **beep sound** is for transactions between the bid and the ask (white color)
   - Hitting the bid is "**Sell!**" (Red)
   - The **ambulance siren sound**  is for hitting below the bid (magenta color)
   - **pitch variations** indicate the second threshold in size was hit (e.g., there might be a filter only showing trades above $10K but a special pitch variation if above $100K in size)

---

Below are a few common libraries or approaches for more robust pitch shifting in Python. Since your files are quite short (< 2 seconds) and can be mono or stereo, you won’t necessarily need a heavy real-time DSP engine. However, if you care about smooth interpolation (e.g., to avoid “choppy” or “clicky” artifacts), these libraries can help:

1. **librosa**  
   - **What it is**: A popular Python library for music and audio analysis.  
   - **Why it helps**: Includes high-level utilities for resampling and pitch-shifting with proper interpolation. For example, `librosa.effects.pitch_shift(y, sr, n_steps)` can shift pitch by fractional semitones without harsh artifacts.  
   - **When to consider**: If you want a straightforward, higher-quality offline pitch shift for short clips. Perfect for 2-second sound effects.

2. **pydub**  
   - **What it is**: A simple, high-level library for audio manipulation (concatenation, slicing, fading, etc.).  
   - **Why it helps**: You can change the frame rate (speed) of the audio, effectively shifting pitch. It doesn’t do advanced formant-preserving pitch shifting, but it supports basic speed changes with some interpolation that’s usually better than raw index-skipping.  
   - **When to consider**: If you already use pydub for other tasks (e.g., mixing or format conversion), and you just need a quick pitch shift.

3. **pysox (the SoX Python bindings)**  
   - **What it is**: A Python interface to [SoX (Sound eXchange)](http://sox.sourceforge.net/), a powerful command-line audio processing tool.  
   - **Why it helps**: SoX can do high-quality resampling, pitch shifting, and other DSP transformations. The bindings let you run SoX’s audio processing from Python without manually calling subprocesses.  
   - **When to consider**: If you’re comfortable with SoX’s command-line style or want SoX’s well-tested DSP algorithms from Python.

4. **Custom `scipy` Resampling**  
   - **What it is**: Using `scipy.signal.resample` or `resample_poly` to do fractional resampling.  
   - **Why it helps**: With a proper filter, `resample_poly` can produce smoother results than naive integer indexing.  
   - **When to consider**: If you want to keep dependencies minimal (only `numpy`/`scipy`) and are comfortable writing some boilerplate code for pitch shifting.

---

## Why a More Advanced Method Helps

In the current method, I am creating a new array of samples by:

```python
new_indices = np.arange(0, num_samples, 1.0 / pitch_factor)
new_indices = np.round(new_indices).astype(np.int32)
pitched_array = sound_array[new_indices]
```

- **Pro**: Very simple, fast for short files.  
- **Con**: Skipping or repeating samples without smoothing often causes artifacts, especially for stereo audio where the two channels must stay in sync.  
- **Con**: For large pitch changes (e.g. 1.5×, 0.8×), you could get “jumpy” waveforms or harsh edges.

Libraries like **librosa** or **SoX** handle *interpolation* so you don’t just jump to the nearest integer sample index. This leads to smoother results even with extreme pitch shifts.

---

## Final Thoughts

- For short one-shot sounds (like 2-second effects), my naive approach might be *good enough*—especially if the pitch factor isn’t extreme and you’re doing it just once.  
- If you want the best audio quality or plan to pitch-shift more complex/longer files, try **librosa** or **SoX** (via **pysox**).  
- Since these sounds are short, I probably don’t need real-time streaming DSP engines (like [**pyo**](https://pypi.org/project/pyo/)) unless I want dynamic pitch manipulation on the fly.  

Depending on your specific needs (quality vs. simplicity), any of these approaches can work better than naive index-skipping.
