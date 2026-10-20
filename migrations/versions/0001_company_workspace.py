"""company workspace: tenancy, imports, predictions, retention

Revision ID: 0001_company_workspace
Revises:
Create Date: 2026-10-16

Safety notes
------------
* Non-destructive only: ADD COLUMN / CREATE TABLE / CREATE INDEX.
* No DROP TABLE, TRUNCATE, or DELETE. All 7,032 IBM sample rows survive.
* Existing customers keep company_id = NULL and are labelled source='ibm_sample'.
* The only removal is the *index* `customer_id`, which is replaced by the
  composite unique (company_id, customer_id). Required for multi-tenancy: two
  companies may legitimately both have customer 'C0001'. Verified 0 duplicate
  customer_id values before writing this migration.
* MySQL DDL is non-transactional, so upgrade() runs every precondition check
  in _preflight() BEFORE the first DDL statement. If a check fails nothing has
  been applied yet and Alembic can be retried or rolled back cleanly.
* downgrade() refuses to run once company operational data exists, rather than
  silently dropping import/prediction/retention tables.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0001_company_workspace"
down_revision = None
branch_labels = None
depends_on = None


CHARSET = "utf8mb4"
COLLATE = "utf8mb4_0900_ai_ci"

# Every table whose rows would be destroyed by downgrade(). This MUST stay in
# sync with the op.drop_table() calls at the top of downgrade(); `companies` is
# included because a registered company exists before it imports anything.
_OPERATIONAL_TABLES = (
    "companies",
    "import_batches",
    "prediction_runs",
    "predictions",
    "retention_cases",
    "retention_notes",
)


def _preflight():
    """Validate every assumption before issuing a single DDL statement.

    MySQL does not wrap DDL in a transaction, so a failure part-way through
    upgrade() leaves the schema half-applied, Alembic records no revision, and
    `flask db downgrade` then refuses to run ("Relative revision -1 didn't
    produce 1 migrations"). The only safe recovery is a restore from backup.
    Aborting here instead means a violated assumption costs nothing.
    """
    bind = op.get_bind()

    # `users` must be empty. Adding `company_id INT NOT NULL` to a populated
    # table silently backfills 0, which points at no company and then makes the
    # foreign key at step 3 impossible to create.
    users = bind.execute(sa.text("SELECT COUNT(*) FROM users")).scalar()
    if users:
        raise RuntimeError(
            f"Refusing to migrate: `users` contains {users} row(s). "
            "users.company_id is added as NOT NULL and cannot be backfilled "
            "safely. Create the company and assign each user to it first "
            "(or run this migration against an empty users table)."
        )

    # Composite uniqueness on (company_id, customer_id) is only safe while the
    # existing single-column customer_id values are already distinct.
    duplicates = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT customer_id FROM customers "
            "GROUP BY customer_id HAVING COUNT(*) > 1) d"
        )
    ).scalar()
    if duplicates:
        raise RuntimeError(
            f"Refusing to migrate: customers has {duplicates} duplicate "
            "customer_id value(s); (company_id, customer_id) uniqueness "
            "cannot be created safely."
        )

    # The target tables must not already exist, which would mean a previous run
    # failed part-way and left residue behind.
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in _OPERATIONAL_TABLES:
        if table in existing:
            raise RuntimeError(
                f"Refusing to migrate: table `{table}` already exists. "
                "This looks like a previously failed or partially applied "
                "migration. Restore from backup before retrying."
            )


def upgrade():
    _preflight()

    # ------------------------------------------------------------------
    # 1. companies - the tenant root
    # ------------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Names are NOT globally unique (approved decision); the slug is.
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("slug", name="uq_companies_slug"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )

    # ------------------------------------------------------------------
    # 2. customers - add ownership, keep IBM rows as sample data
    # ------------------------------------------------------------------
    op.add_column(
        "customers",
        sa.Column("company_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "customers",
        # Every pre-existing row is IBM sample data. NULL company_id is the
        # marker; source makes it explicit and queryable.
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="ibm_sample",
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column(
        "customers",
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NULL"),
            nullable=True,
        ),
    )

    # Replace global uniqueness with per-company uniqueness.
    op.drop_index("customer_id", table_name="customers")
    op.create_index(
        "uq_customers_company_customer",
        "customers",
        ["company_id", "customer_id"],
        unique=True,
    )
    op.create_index("ix_customers_company", "customers", ["company_id"])
    op.create_index("ix_customers_source", "customers", ["source"])

    op.create_foreign_key(
        "fk_customers_company",
        "customers",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ------------------------------------------------------------------
    # 3. users - ownership, activity flag, Viewer role
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=False))
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
    )
    # Add 'Viewer' to the existing enum. MySQL needs the full list re-declared.
    op.execute(
        "ALTER TABLE users MODIFY COLUMN role "
        "ENUM('Admin','Analyst','Viewer') NOT NULL DEFAULT 'Analyst'"
    )
    op.create_index("ix_users_company", "users", ["company_id"])
    op.create_foreign_key(
        "fk_users_company",
        "users",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # email stays globally unique: one login belongs to exactly one company.

    # ------------------------------------------------------------------
    # 4. import_batches - one uploaded file per import attempt
    # ------------------------------------------------------------------
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "uploaded", "validated", "previewed",
                "imported", "failed", "rejected",
                name="import_status",
            ),
            server_default="uploaded",
            nullable=False,
        ),
        # Survives the request so the user can review before committing.
        sa.Column("staged_path", sa.String(length=512), nullable=True),
        # {csv column -> model field key} chosen by the user.
        sa.Column("column_mapping", mysql.JSON(), nullable=True),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("rejected_path", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    op.create_index("ix_import_batches_company", "import_batches", ["company_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_foreign_key(
        "fk_import_batches_company", "import_batches", "companies",
        ["company_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_import_batches_user", "import_batches", "users",
        ["created_by"], ["id"], ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 5. prediction_runs - one bulk scoring pass
    # ------------------------------------------------------------------
    op.create_table(
        "prediction_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "running", "completed",
                "completed_with_errors", "failed",
                name="prediction_run_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        # e.g. "gradboost-30f-<sha8>" so results stay attributable.
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("total_customers", sa.Integer(), server_default="0", nullable=False),
        sa.Column("predicted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("churn_predicted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retained_predicted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prediction_runs"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    op.create_index("ix_prediction_runs_company", "prediction_runs", ["company_id"])
    op.create_index(
        "ix_prediction_runs_company_created", "prediction_runs", ["company_id", "created_at"]
    )
    op.create_foreign_key(
        "fk_prediction_runs_company", "prediction_runs", "companies",
        ["company_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_prediction_runs_batch", "prediction_runs", "import_batches",
        ["import_batch_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_prediction_runs_user", "prediction_runs", "users",
        ["created_by"], ["id"], ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 6. predictions - per-customer model output
    #
    # `churn` on customers stays the ACTUAL ground-truth label (nullable for
    # imported company data). The model output lives here and is never
    # conflated with it.
    # ------------------------------------------------------------------
    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("prediction_run_id", sa.Integer(), nullable=False),
        sa.Column("customer_pk", sa.Integer(), nullable=False),
        # Snapshot of the business id, so history survives customer edits.
        sa.Column("customer_ref", sa.String(length=64), nullable=False),
        sa.Column(
            "churn_probability",
            sa.DECIMAL(precision=5, scale=2),
            nullable=False,
        ),
        sa.Column("predicted_churn", sa.Enum("Yes", "No", name="predicted_churn"), nullable=False),
        sa.Column(
            "risk_category",
            sa.Enum("low", "medium", "high", name="risk_category"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "predicted_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_predictions"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    # One prediction per customer per run -> re-running a run cannot duplicate.
    op.create_unique_constraint(
        "uq_predictions_run_customer",
        "predictions",
        ["prediction_run_id", "customer_pk"],
    )
    op.create_index("ix_predictions_company", "predictions", ["company_id"])
    op.create_index(
        "ix_predictions_company_risk", "predictions", ["company_id", "risk_category"]
    )
    op.create_index(
        "ix_predictions_company_outcome", "predictions", ["company_id", "predicted_churn"]
    )
    op.create_index("ix_predictions_customer", "predictions", ["customer_pk"])
    op.create_foreign_key(
        "fk_predictions_company", "predictions", "companies",
        ["company_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_predictions_run", "predictions", "prediction_runs",
        ["prediction_run_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_predictions_customer", "predictions", "customers",
        ["customer_pk"], ["id"], ondelete="CASCADE",
    )

    # ------------------------------------------------------------------
    # 7. retention_cases - at-risk follow-up workflow
    # ------------------------------------------------------------------
    op.create_table(
        "retention_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("customer_pk", sa.Integer(), nullable=False),
        sa.Column("prediction_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "Pending", "Contacted", "Retention Offer",
                "Retained", "Closed", "Cancelled",
                name="retention_status",
            ),
            server_default="Pending",
            nullable=False,
        ),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_retention_cases"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    op.create_index("ix_retention_cases_company", "retention_cases", ["company_id"])
    op.create_index("ix_retention_cases_status", "retention_cases", ["company_id", "status"])
    op.create_index("ix_retention_cases_customer", "retention_cases", ["customer_pk"])
    op.create_foreign_key(
        "fk_retention_cases_company", "retention_cases", "companies",
        ["company_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_retention_cases_customer", "retention_cases", "customers",
        ["customer_pk"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_retention_cases_prediction", "retention_cases", "predictions",
        ["prediction_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_retention_cases_assignee", "retention_cases", "users",
        ["assigned_to"], ["id"], ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 8. retention_notes - timestamped follow-up log
    # ------------------------------------------------------------------
    op.create_table(
        "retention_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("retention_case_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_retention_notes"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    op.create_index("ix_retention_notes_case", "retention_notes", ["retention_case_id"])
    op.create_foreign_key(
        "fk_retention_notes_case", "retention_notes", "retention_cases",
        ["retention_case_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_retention_notes_author", "retention_notes", "users",
        ["author_id"], ["id"], ondelete="SET NULL",
    )


def _assert_no_operational_data():
    """Refuse to drop tables that hold real company data.

    downgrade() drops every table listed in _OPERATIONAL_TABLES: companies,
    import_batches, prediction_runs, predictions, retention_cases and
    retention_notes. That is correct while they are empty, but it would
    silently destroy company registrations, uploads, predictions and retention
    history once they are in use.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    populated = []
    for table in _OPERATIONAL_TABLES:
        if table not in existing:
            continue
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM `{table}`")).scalar()
        if count:
            populated.append(f"{table}={count}")

    if populated:
        raise RuntimeError(
            "Refusing to downgrade: operational data exists ("
            + ", ".join(populated)
            + "). Downgrade would permanently delete it. Export and archive "
            "the data first, then re-run with the tables emptied."
        )


def downgrade():
    _assert_no_operational_data()

    # Reverse order, children before parents.
    op.drop_table("retention_notes")
    op.drop_table("retention_cases")
    op.drop_table("predictions")
    op.drop_table("prediction_runs")
    op.drop_table("import_batches")

    # users: restore the original two-value enum and drop tenancy columns.
    op.drop_constraint("fk_users_company", "users", type_="foreignkey")
    op.drop_index("ix_users_company", table_name="users")
    op.drop_column("users", "is_active")
    op.drop_column("users", "company_id")
    op.execute("ALTER TABLE users MODIFY COLUMN role ENUM('Admin','Analyst') NULL DEFAULT 'Analyst'")

    # customers: restore global uniqueness on customer_id.
    op.drop_constraint("fk_customers_company", "customers", type_="foreignkey")
    op.drop_index("ix_customers_source", table_name="customers")
    op.drop_index("ix_customers_company", table_name="customers")
    op.drop_index("uq_customers_company_customer", table_name="customers")
    op.create_index("customer_id", "customers", ["customer_id"], unique=True)
    op.drop_column("customers", "updated_at")
    op.drop_column("customers", "created_at")
    op.drop_column("customers", "source")
    op.drop_column("customers", "company_id")

    op.drop_table("companies")
