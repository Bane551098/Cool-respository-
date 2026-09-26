# Particle Dojo

A WaniKani-style study app for Japanese particles, prefixes and honorifics
(は, の, を, お, ご, さん, ちゃん, くん, 様, 不, 超, 的 and more — 64 items in 7 groups).

Open `index.html` in any browser. No install or build step.

## How it works

1. **Review** – each group opens with an overview, then a card for every item:
   meaning, when to use it, an example sentence, and the answers the test accepts.
2. **Ready** – press Ready to start the test for that group.
3. **Test** – you see the kanji/kana and romaji, and type the English meaning.
   - Right: it moves straight on to the next word (small typos are accepted).
   - Wrong: tap **Review this word** to see its card. The word comes back later in
     the test until you get it right.
4. **Results** – first-try score, the words you missed, and a retry of just those.

Progress is saved in your browser's local storage.

## Groups

| Group | Examples |
| --- | --- |
| Name Suffixes | さん, ちゃん, くん, 様, 先生, 先輩, 殿, 氏 |
| Polite Prefixes | お, ご, 御 (on / mi), 貴, 弊 |
| Core Particles | は, が, を, に, へ, で, の, と, も, や |
| Range & Limit Particles | から, まで, より, だけ, しか, ほど, など, ぐらい |
| Sentence Endings | か, ね, よ, よね, な, かな, わ, ぞ, ぜ, の |
| Word Prefixes | 不, 無, 未, 非, 再, 超, 新, 毎, 全, 前, 初, 真 |
| Word Suffixes | たち, ら, 人, 語, 屋, 的, 中, 者, 化, 方 |

To add words, edit the `GROUPS` array near the top of the `<script>` in `index.html`.
