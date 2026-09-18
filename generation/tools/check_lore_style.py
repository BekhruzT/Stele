"""Compare a lore transcript's AI tells and flow metrics against a reference: `<transcript.txt> <reference.txt>`."""
import re, statistics, sys

TELLS = {
    "we'll come back/return": r"[Ww]e['\u2019]ll (?:come back|return)|we will (?:come back|return)",
    "meta narration (goes next/this account)": r"goes next|picks? up (?:next|later)|separate thread|this account|this telling|already (?:covered|described)|as already noted|as mentioned earlier|covered on its own",
    "source leak (the material/concepts)": r"the material|the concepts",
    "Meanwhile": r"\bMeanwhile\b",
    "em-dash": r"\u2014",
    "not an abstraction / testament": r"not an abstraction|stands as a testament|little did",
    "stock thesis pivots": r"\bAt its heart\b|\bcrucially\b|it is worth noting|The picture most of us have|And so we come to|To understand (?:that|this),? we need to",
    "negation-first story framing": r"This is not (?:a )?story|It is simply a description",
}


def load(path: str) -> str:
    t = open(path, encoding="utf-8").read()
    # ponytail: only the three entities tag-stripping actually leaves behind, not a full unescape
    return t.replace("&#x27;", "'").replace("&quot;", '"').replace("&middot;", "\u00b7")


def metrics(t: str) -> dict:
    words = t.split()
    n = len(words)
    slens = [len(s.split()) for s in re.split(r"(?<=[.!?])\s+", t) if s.split()]
    m = {
        "words": n,
        "avg sentence words": round(statistics.mean(slens), 1),
        "% sentences >35w": round(100 * sum(1 for x in slens if x > 35) / len(slens), 1),
        "% sentences >38w": round(100 * sum(1 for x in slens if x > 38) / len(slens), 1),
        "% sentences <9w": round(100 * sum(1 for x in slens if x < 9) / len(slens), 1),
    }
    for name, pat in TELLS.items():
        m[name + " /10k"] = round(len(re.findall(pat, t)) / n * 10000, 1)
    return m


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    ours = metrics(load(sys.argv[1]))
    ref = metrics(load(sys.argv[2]))
    print(f"{'metric':44s} {'ref':>8s} {'ours':>8s}")
    for k in ours:
        print(f"{k:44s} {ref[k]:>8} {ours[k]:>8}")


if __name__ == "__main__":
    main()
