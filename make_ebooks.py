"""
Gera os primeiros ebooks do ATLAS (colorir / labirintos / gratidao) em EN e PT.

Uso:
    python make_ebooks.py            # gera todos
    python make_ebooks.py coloring   # so o livro de colorir
    python make_ebooks.py mazes
    python make_ebooks.py gratitude
"""

import os
import sys

sys.path.insert(0, r"C:\atlas-os")
os.chdir(r"C:\atlas-os")

from app.services.ebook_service import EbookService  # noqa: E402


def make_coloring(svc: EbookService):
    return svc.build_coloring_book(
        slug="cute-baby-animals",
        titles={"en": "Cute Baby Animals", "pt": "Animais Fofos para Colorir"},
        subtitles={
            "en": "A Fun Coloring Book for Kids Ages 4-8",
            "pt": "Um Livro de Colorir Divertido para Criancas de 4 a 8 Anos",
        },
        subjects=[
            "a baby elephant", "a fluffy puppy", "a cute kitten", "a baby bunny",
            "a baby panda", "a lion cub", "a baby fox", "a penguin chick",
            "a koala", "a baby owl", "a baby unicorn", "a friendly baby dinosaur",
        ],
        style="cute kawaii style with big friendly eyes, adorable and simple for kids",
        detail="kids",
    )


def make_mazes(svc: EbookService):
    return svc.build_maze_book(
        slug="amazing-mazes-for-kids",
        titles={"en": "Amazing Mazes for Kids", "pt": "Labirintos Incriveis para Criancas"},
        subtitles={
            "en": "Fun Brain-Boosting Puzzles for Ages 6-10",
            "pt": "Desafios Divertidos para a Mente de 6 a 10 Anos",
        },
        count=12,
    )


def make_gratitude(svc: EbookService):
    return svc.build_gratitude_journal(
        slug="daily-gratitude-journal",
        titles={"en": "My Daily Gratitude Journal", "pt": "Meu Diario de Gratidao"},
        subtitles={
            "en": "5 Minutes a Day to a Happier, More Positive You",
            "pt": "5 Minutos por Dia para uma Vida Mais Feliz e Positiva",
        },
        days=30,
    )


def make_adult(svc: EbookService):
    mandalas = [
        "an intricate floral mandala", "a geometric lotus mandala",
        "an ornate circular mandala with leaves", "a symmetrical star mandala",
        "a detailed rose mandala", "a mandala with feathers and swirls",
        "a sun and moon mandala", "a butterfly mandala", "a peacock feather mandala",
        "an arabesque ornamental mandala", "a mandala of interlaced hearts",
        "a snowflake style mandala", "a paisley mandala", "a seashell mandala",
        "a floral wreath mandala",
    ]
    return svc.build_coloring_book(
        slug="mindful-mandalas",
        titles={"en": "Mindful Mandalas", "pt": "Mandalas Relaxantes"},
        subtitles={
            "en": "Stress-Relief Coloring Book for Adults",
            "pt": "Livro de Colorir Antiestresse para Adultos",
        },
        subjects=mandalas,
        style="symmetrical ornamental, bold clean lines, intricate detail",
        detail="adult",
    )


def make_meal(svc: EbookService):
    return svc.build_meal_planner(
        slug="weekly-meal-planner",
        titles={"en": "Weekly Meal Planner", "pt": "Planejador de Refeicoes"},
        subtitles={
            "en": "Plan Your Meals and Shopping with Ease",
            "pt": "Planeje suas Refeicoes e Compras com Facilidade",
        },
        weeks=13,
    )


def make_recipes(svc: EbookService):
    return svc.build_recipe_book(
        slug="easy-air-fryer-recipes",
        titles={"en": "Easy Air Fryer Recipes", "pt": "Receitas Faceis na Air Fryer"},
        subtitles={
            "en": "Quick, Healthy and Delicious Everyday Meals",
            "pt": "Refeicoes Rapidas, Saudaveis e Deliciosas do Dia a Dia",
        },
        theme="air fryer",
        count=12,
    )


def main():
    target = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    svc = EbookService()
    jobs = {
        "coloring": make_coloring,
        "mazes": make_mazes,
        "gratitude": make_gratitude,
        "adult": make_adult,
        "meal": make_meal,
        "recipes": make_recipes,
    }
    todo = jobs.items() if target == "all" else [(target, jobs[target])]
    for name, fn in todo:
        print(f"\n=== {name} ===")
        res = fn(svc)
        print("RESULT:", res)


if __name__ == "__main__":
    main()
