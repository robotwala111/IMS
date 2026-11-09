"""Add explicit numeric cut-film quantity to jobs."""

from alembic import op
import sqlalchemy as sa

revision = "037_job_cut_films_count"
down_revision = "036_audit_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("cut_films_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_jobs_nonnegative_results", "jobs",
        "(accepted IS NULL OR accepted >= 0) AND (reshoot IS NULL OR reshoot >= 0) "
        "AND (cut_films_count IS NULL OR cut_films_count >= 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_nonnegative_results", "jobs", type_="check")
    op.drop_column("jobs", "cut_films_count")
