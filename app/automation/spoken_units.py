from __future__ import annotations

import re


_PT_UNITS = {
    "ml": ("mililitro", "mililitros"),
    "cl": ("centilitro", "centilitros"),
    "dl": ("decilitro", "decilitros"),
    "l": ("litro", "litros"),
    "kw": ("quilowatt", "quilowatts"),
    "w": ("watt", "watts"),
    "v": ("volt", "volts"),
    "ma": ("miliampere", "miliamperes"),
    "a": ("ampere", "amperes"),
    "mah": ("miliampere-hora", "miliamperes-hora"),
    "ah": ("ampere-hora", "amperes-hora"),
    "kwh": ("quilowatt-hora", "quilowatts-hora"),
    "wh": ("watt-hora", "watts-hora"),
    "mm": ("milimetro", "milimetros"),
    "cm": ("centimetro", "centimetros"),
    "km": ("quilometro", "quilometros"),
    "m": ("metro", "metros"),
    "mg": ("miligrama", "miligramas"),
    "kg": ("quilograma", "quilogramas"),
    "g": ("grama", "gramas"),
    "lb": ("libra", "libras"),
    "lbs": ("libra", "libras"),
    "oz": ("onca", "oncas"),
    "tb": ("terabyte", "terabytes"),
    "gb": ("gigabyte", "gigabytes"),
    "mb": ("megabyte", "megabytes"),
    "kb": ("quilobyte", "quilobytes"),
    "ghz": ("gigahertz", "gigahertz"),
    "mhz": ("megahertz", "megahertz"),
    "khz": ("quilohertz", "quilohertz"),
    "hz": ("hertz", "hertz"),
    "rpm": ("rotacao por minuto", "rotacoes por minuto"),
    "psi": ("psi", "psi"),
    "db": ("decibel", "decibeis"),
    "lm": ("lumen", "lumens"),
    "mp": ("megapixel", "megapixels"),
}

_EN_UNITS = {
    "ml": ("milliliter", "milliliters"),
    "cl": ("centiliter", "centiliters"),
    "dl": ("deciliter", "deciliters"),
    "l": ("liter", "liters"),
    "kw": ("kilowatt", "kilowatts"),
    "w": ("watt", "watts"),
    "v": ("volt", "volts"),
    "ma": ("milliamp", "milliamps"),
    "a": ("amp", "amps"),
    "mah": ("milliamp hour", "milliamp hours"),
    "ah": ("amp hour", "amp hours"),
    "kwh": ("kilowatt hour", "kilowatt hours"),
    "wh": ("watt hour", "watt hours"),
    "mm": ("millimeter", "millimeters"),
    "cm": ("centimeter", "centimeters"),
    "km": ("kilometer", "kilometers"),
    "m": ("meter", "meters"),
    "mg": ("milligram", "milligrams"),
    "kg": ("kilogram", "kilograms"),
    "g": ("gram", "grams"),
    "lb": ("pound", "pounds"),
    "lbs": ("pound", "pounds"),
    "oz": ("ounce", "ounces"),
    "tb": ("terabyte", "terabytes"),
    "gb": ("gigabyte", "gigabytes"),
    "mb": ("megabyte", "megabytes"),
    "kb": ("kilobyte", "kilobytes"),
    "ghz": ("gigahertz", "gigahertz"),
    "mhz": ("megahertz", "megahertz"),
    "khz": ("kilohertz", "kilohertz"),
    "hz": ("hertz", "hertz"),
    "rpm": ("revolution per minute", "revolutions per minute"),
    "psi": ("P S I", "P S I"),
    "db": ("decibel", "decibels"),
    "lm": ("lumen", "lumens"),
    "mp": ("megapixel", "megapixels"),
}

_UNIT_PATTERN = "|".join(
    sorted(
        {re.escape(unit) for unit in _PT_UNITS},
        key=len,
        reverse=True,
    )
)
_NUMBER = r"\d+(?:[.,]\d+)?"

# Mobile network generations (2G/3G/4G/5G/6G) must be read as the letter "G",
# never expanded to "gramas"/"grams". Uppercase "G" is always connectivity;
# a lowercase "5g" is only connectivity when the text talks about networks/phones.
_NETWORK_GEN_KEYWORDS = (
    "rede",
    "redes",
    "conexao",
    "conexão",
    "conexoes",
    "conexões",
    "internet",
    "movel",
    "móvel",
    "celular",
    "celulares",
    "smartphone",
    "smartphones",
    "wifi",
    "wi-fi",
    "lte",
    "banda larga",
    "operadora",
    "network",
    "mobile",
    "phone",
    "cellular",
    "connectivity",
)
_NETWORK_GEN_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ0-9])(?P<gen>[2-6])\s?(?P<g>[gG])(?![A-Za-zÀ-ÿ0-9])"
)


def _protect_network_generations(value: str) -> str:
    """Replace 2G-6G tokens with a sentinel so the grams rule skips them."""
    has_context = any(keyword in value.lower() for keyword in _NETWORK_GEN_KEYWORDS)

    def _protect(match: re.Match[str]) -> str:
        # Lowercase "g" only counts as a network generation with clear context;
        # otherwise keep it as a genuine weight in grams.
        if match.group("g") == "g" and not has_context:
            return match.group(0)
        return f"\x00NGEN{match.group('gen')}\x00"

    return _NETWORK_GEN_RE.sub(_protect, value)


def _restore_network_generations(value: str) -> str:
    return re.sub(r"\x00NGEN(?P<gen>[2-6])\x00", r"\g<gen>G", value)


def _is_singular(number: str) -> bool:
    try:
        return float(number.replace(",", ".")) == 1.0
    except ValueError:
        return False


def expand_spoken_units(text: str, language: str = "pt") -> str:
    """Expande abreviacoes numericas para uma pronuncia natural no TTS."""
    value = str(text or "")
    if not value:
        return ""

    is_portuguese = not str(language or "").lower().startswith(("en", "us"))
    units = _PT_UNITS if is_portuguese else _EN_UNITS
    dimension_word = " por " if is_portuguese else " by "

    value = _protect_network_generations(value)

    value = re.sub(
        rf"(?<=\d)\s*[x\u00d7]\s*(?=\d)",
        dimension_word,
        value,
        flags=re.IGNORECASE,
    )

    def replace_unit(match: re.Match[str]) -> str:
        number = match.group("number")
        unit = match.group("unit").lower()
        spoken = units[unit][0 if _is_singular(number) else 1]
        if is_portuguese:
            number = number.replace(".", ",")
        return f"{number} {spoken}"

    value = re.sub(
        rf"(?<![A-Za-zÀ-ÿ0-9])"
        rf"(?P<number>{_NUMBER})\s*(?P<unit>{_UNIT_PATTERN})(?![A-Za-zÀ-ÿ])",
        replace_unit,
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        rf"(?<![A-Za-zÀ-ÿ0-9])(?P<number>{_NUMBER})\s*\u00b0\s*C\b",
        lambda match: (
            f"{match.group('number').replace('.', ',')} graus Celsius"
            if is_portuguese
            else f"{match.group('number')} degrees Celsius"
        ),
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf"(?<![A-Za-zÀ-ÿ0-9])(?P<number>{_NUMBER})\s*\u00b0\s*F\b",
        lambda match: (
            f"{match.group('number').replace('.', ',')} graus Fahrenheit"
            if is_portuguese
            else f"{match.group('number')} degrees Fahrenheit"
        ),
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        rf'(?<![A-Za-zÀ-ÿ0-9])'
        rf'(?P<number>{_NUMBER})\s*(?:"|pol(?:\.|egadas?)?)',
        lambda match: (
            f"{match.group('number').replace('.', ',')} "
            f"{'polegada' if _is_singular(match.group('number')) else 'polegadas'}"
            if is_portuguese
            else f"{match.group('number')} "
            f"{'inch' if _is_singular(match.group('number')) else 'inches'}"
        ),
        value,
        flags=re.IGNORECASE,
    )
    value = _restore_network_generations(value)
    return re.sub(r"\s{2,}", " ", value).strip()
