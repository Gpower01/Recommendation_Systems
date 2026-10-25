"""Movie recommendations using the MovieLens 100K ratings dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from flask import Flask, render_template, request


DEFAULT_MOVIES = ("Star Wars (1977)", "Liar Liar (1997)")


def load_ratings(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the MovieLens ratings and return the joined data and movie summary."""
    ratings_path = data_dir / "u.data"
    titles_path = data_dir / "Movie_Id_Titles"

    missing_files = [path for path in (ratings_path, titles_path) if not path.is_file()]
    if missing_files:
        missing = ", ".join(str(path) for path in missing_files)
        raise FileNotFoundError(f"Required MovieLens file(s) not found: {missing}")

    user_ratings = pd.read_csv(
        ratings_path,
        sep="\t",
        names=["user_id", "item_id", "rating", "timestamp"],
    )
    movie_titles = pd.read_csv(titles_path)

    required_columns = {"item_id", "title"}
    if not required_columns.issubset(movie_titles.columns):
        raise ValueError(
            f"{titles_path} must contain columns: {', '.join(sorted(required_columns))}"
        )

    data = user_ratings.merge(movie_titles[["item_id", "title"]], on="item_id")
    movie_summary = data.groupby("title")["rating"].agg(
        mean_rating="mean",
        rating_count="count",
    )
    return data, movie_summary


def recommend_movies(
    data: pd.DataFrame,
    movie_summary: pd.DataFrame,
    movie_title: str,
    min_ratings: int,
    limit: int,
) -> pd.DataFrame:
    """Rank movies by rating correlation with the selected movie."""
    movie_matrix = data.pivot_table(
        index="user_id",
        columns="title",
        values="rating",
    )
    if movie_title not in movie_matrix.columns:
        raise ValueError(f"Movie not found in the dataset: {movie_title}")

    correlations = movie_matrix.corrwith(movie_matrix[movie_title]).rename("correlation")
    recommendations = correlations.to_frame().join(movie_summary).dropna()
    recommendations = recommendations[
        (recommendations["rating_count"] > min_ratings)
        & (recommendations.index != movie_title)
    ]
    return recommendations.sort_values("correlation", ascending=False).head(limit)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Movie recommendations from the MovieLens 100K dataset.",
        epilog=(
            'Examples: python app.py; python app.py --cli --movie "Toy Story (1995)"'
        ),
    )
    parser.add_argument(
        "--movie",
        action="append",
        dest="movies",
        help=(
            "Movie title to use as the recommendation seed. Repeat this option "
            "to analyze more than one movie. Defaults to Star Wars and Liar Liar."
        ),
    )
    parser.add_argument(
        "--min-ratings",
        type=int,
        default=100,
        help="Require more than this many ratings for a recommended movie (default: 100).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum recommendations per movie (default: 10).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "Datasets",
        help="Directory containing u.data and Movie_Id_Titles.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Print recommendations in the terminal instead of starting the web app.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Local web server address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Local web server port (default: 5000).",
    )
    return parser


def create_web_app(data_dir: Path) -> Flask:
    data, movie_summary = load_ratings(data_dir)
    movie_matrix = data.pivot_table(index="user_id", columns="title", values="rating")
    app = Flask(__name__)
    movie_titles = sorted(movie_matrix.columns.tolist())

    @app.get("/")
    def home():
        selected_movie = request.args.get("movie", "Star Wars (1977)")
        min_ratings = request.args.get("min_ratings", default=100, type=int)
        limit = request.args.get("limit", default=10, type=int)
        recommendations = None
        error = None

        if min_ratings < 0 or limit < 1:
            error = "The rating threshold must be zero or higher and result count must be at least 1."
        elif selected_movie not in movie_matrix.columns:
            error = "Choose a movie from the list."
        else:
            correlations = movie_matrix.corrwith(movie_matrix[selected_movie]).rename("correlation")
            recommendations = correlations.to_frame().join(movie_summary).dropna()
            recommendations = recommendations[
                (recommendations["rating_count"] > min_ratings)
                & (recommendations.index != selected_movie)
            ].sort_values("correlation", ascending=False).head(limit)
            recommendations = recommendations.reset_index().to_dict(orient="records")

        return render_template(
            "index.html",
            movie_titles=movie_titles,
            selected_movie=selected_movie,
            min_ratings=min_ratings,
            limit=limit,
            recommendations=recommendations,
            error=error,
        )

    return app


def run_cli(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:

    if args.min_ratings < 0:
        parser.error("--min-ratings must be zero or greater")
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    try:
        data, movie_summary = load_ratings(args.data_dir)
        for movie_title in args.movies or DEFAULT_MOVIES:
            recommendations = recommend_movies(
                data,
                movie_summary,
                movie_title,
                args.min_ratings,
                args.limit,
            )
            print(f"\nMovies similar to {movie_title}:")
            if recommendations.empty:
                print("No recommendations match the current rating threshold.")
                continue

            print(
                recommendations.reset_index()[
                    ["title", "correlation", "mean_rating", "rating_count"]
                ].to_string(
                    index=False,
                    formatters={"correlation": "{:.3f}".format, "mean_rating": "{:.2f}".format},
                )
            )
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.cli:
        return run_cli(args, parser)

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    try:
        web_app = create_web_app(args.data_dir)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    print(f"Movie recommender is running at http://{args.host}:{args.port}")
    web_app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())