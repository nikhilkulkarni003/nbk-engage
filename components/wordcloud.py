"""Word cloud image rendering from pre-computed word frequencies
(services.analytics.get_word_frequencies)."""

from __future__ import annotations

import io
import random

import streamlit as st
from wordcloud import WordCloud

# Bright, varied palette (pinks/blues/oranges/greens/teals/purples) --
# each word gets a random color from this set rather than a single
# gradient colormap, matching a classic multi-color tag-cloud look.
PALETTE = [
    "#FF6B9D", "#4EA8DE", "#FF9F45", "#43C6AC", "#845EC2",
    "#FFC75F", "#00C2A8", "#F86C6C", "#5C7CFA", "#37B24D",
    "#E64980", "#1C9BEF", "#F76707", "#0CA678", "#7048E8",
]


def _random_color_func(word=None, font_size=None, position=None,
                        orientation=None, font_path=None, random_state=None):
    return random.choice(PALETTE)


def render_wordcloud(word_freq: list[dict], total_responses: int) -> None:
    st.caption(f"💬 {total_responses} response(s) submitted")

    if not word_freq:
        st.info("No responses yet. Words will appear here as participants submit them.")
        return

    freq_dict = {item["word"]: item["count"] for item in word_freq}

    wc = WordCloud(
        width=1400,
        height=700,
        scale=2,                    # crisp on a projector without bloating layout size
        mode="RGBA",
        background_color=None,      # transparent -- no border, no baked-in title
        color_func=_random_color_func,
        prefer_horizontal=0.92,     # mostly horizontal, a few rotated for texture
        relative_scaling=0.55,      # size differences read clearly without huge outliers
        margin=2,                   # tightly packed, minimal gaps
        max_words=100,
        font_step=1,
        collocations=False,
    ).generate_from_frequencies(freq_dict)

    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    st.image(buf.getvalue(), use_container_width=True)

    with st.expander("Word frequency table"):
        st.dataframe(
            [{"Word": w["word"], "Count": w["count"]} for w in word_freq[:30]],
            hide_index=True,
            use_container_width=True,
        )
