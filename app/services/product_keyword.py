"""Gera a "palavra-gatilho" de cada produto.

A mesma palavra precisa aparecer na legenda (Instagram/Facebook) e na lista
que o robo de direct usa. Por isso a logica fica AQUI, num lugar so, e e
importada pelos dois lados (publicacao e geracao da bio).

Regra: pega a palavra mais "cara do produto" do titulo (a primeira palavra
util, sem acento, so letras), em MAIUSCULA. Ex.:
    "Fritadeira Air Fryer Mondial 4L" -> "FRITADEIRA"
    "Echo Dot 5a geracao"             -> "ECHO"
Se nao achar nada util, usa o ASIN como reserva.
"""
from __future__ import annotations

import re
import unicodedata

# Palavras genericas que NAO servem como gatilho (nao identificam o produto).
_STOPWORDS = {
    "the", "and", "for", "with", "new", "kit", "pro", "max", "plus", "mini",
    "com", "para", "de", "da", "do", "dos", "das", "e", "a", "o", "os", "as",
    "um", "uma", "amazon", "original", "oficial", "un", "und", "pcs", "set",
}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def product_keyword(title: str, asin: str = "") -> str:
    """Retorna a palavra-gatilho (MAIUSCULA, so letras A-Z, ate 14 chars)."""
    clean = _strip_accents(str(title or ""))
    # Quebra em palavras so de letras (ignora numeros, /, -, etc.).
    words = re.findall(r"[A-Za-z]+", clean)
    for w in words:
        wl = w.lower()
        if len(w) >= 4 and wl not in _STOPWORDS:
            return w.upper()[:14]
    # Nenhuma palavra "boa": tenta a primeira palavra qualquer.
    for w in words:
        if w.lower() not in _STOPWORDS:
            return w.upper()[:14]
    # Ultima reserva: usa o ASIN (ou LINK).
    a = re.sub(r"[^A-Za-z0-9]", "", str(asin or "")).upper()
    return a[:14] or "LINK"
