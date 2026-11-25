from hasesa_api.models import Base

# Tables the web app created with Drizzle. The models must keep every one.
WEB_APP_TABLES = {
    "users",
    "experiment_progress",
    "conversations",
    "messages",
    "page_views",
    "usage",
    "payments",
    "module_enrollments",
    "step_progress",
    "unit_progress",
    "question_attempts",
    "signoffs",
    "guide_feedback",
    "unit_assignments",
}


def test_models_cover_every_web_app_table() -> None:
    assert WEB_APP_TABLES <= set(Base.metadata.tables)


def test_unique_indexes_match_drizzle() -> None:
    users = Base.metadata.tables["users"]
    unique = {ix.name for ix in users.indexes if ix.unique}
    assert unique == {"users_email_lower_idx", "users_google_sub_idx"}
    signoffs = Base.metadata.tables["signoffs"]
    assert {ix.name for ix in signoffs.indexes if ix.unique} == {"signoffs_code_idx"}
