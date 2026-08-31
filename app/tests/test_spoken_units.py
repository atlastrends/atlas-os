from unittest import TestCase

from app.automation.spoken_units import expand_spoken_units


class ExpandSpokenUnitsTests(TestCase):
    def test_expands_portuguese_product_measurements(self):
        text = (
            "Reservatorio de 5L, potencia de 200W, 220V e tamanho "
            "30x20x10cm. Pesa 2kg e tem tela de 55\"."
        )

        self.assertEqual(
            expand_spoken_units(text, "pt-BR"),
            (
                "Reservatorio de 5 litros, potencia de 200 watts, 220 volts "
                "e tamanho 30 por 20 por 10 centimetros. Pesa 2 quilogramas "
                "e tem tela de 55 polegadas."
            ),
        )

    def test_uses_singular_and_portuguese_decimal_separator(self):
        self.assertEqual(
            expand_spoken_units("Capacidade de 1L e cabo de 1.5m.", "pt"),
            "Capacidade de 1 litro e cabo de 1,5 metros.",
        )

    def test_expands_english_product_measurements(self):
        self.assertEqual(
            expand_spoken_units("5L tank, 200W motor and 30x20cm body.", "en-US"),
            "5 liters tank, 200 watts motor and 30 by 20 centimeters body.",
        )

    def test_does_not_change_letters_without_a_number(self):
        self.assertEqual(
            expand_spoken_units("Modelo W com tamanho L.", "pt-BR"),
            "Modelo W com tamanho L.",
        )

    def test_does_not_interpret_model_codes_as_measurements(self):
        text = (
            "A Samsung WD11M e a WD11M4473PX lavam 11kg, enquanto a "
            "Galaxy M55 tem bateria de 5000mAh."
        )

        self.assertEqual(
            expand_spoken_units(text, "pt-BR"),
            (
                "A Samsung WD11M e a WD11M4473PX lavam 11 quilogramas, "
                "enquanto a Galaxy M55 tem bateria de 5000 miliamperes-hora."
            ),
        )

    def test_network_generation_is_not_read_as_grams(self):
        self.assertEqual(
            expand_spoken_units("Celular 5G com rede 4G/5G ultrarrapida.", "pt-BR"),
            "Celular 5G com rede 4G/5G ultrarrapida.",
        )

    def test_uppercase_generation_without_context_stays_network(self):
        self.assertEqual(
            expand_spoken_units("Suporta 5G e 4G.", "en-US"),
            "Suporta 5G e 4G.",
        )

    def test_lowercase_grams_still_expands_without_network_context(self):
        self.assertEqual(
            expand_spoken_units("Cada porcao tem 5g de proteina.", "pt-BR"),
            "Cada porcao tem 5 gramas de proteina.",
        )

    def test_lowercase_generation_with_context_is_network(self):
        self.assertEqual(
            expand_spoken_units("Smartphone com internet 5g veloz.", "pt-BR"),
            "Smartphone com internet 5G veloz.",
        )
