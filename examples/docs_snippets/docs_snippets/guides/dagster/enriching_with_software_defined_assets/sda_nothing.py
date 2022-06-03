from mylib import create_db_connection, pickle_to_s3, train_recommender_model
from pandas import read_sql

from dagster import AssetSelection, asset, assets_from_current_module, repository


@asset(non_argument_deps={"raw_users"})
def users():
    raw_users_df = read_sql(f"select * from raw_users", con=create_db_connection())
    users_df = raw_users_df.dropna()
    users_df.to_sql(name="users", con=create_db_connection())


@asset(non_argument_deps={"users"})
def user_recommender_model():
    users_df = read_sql(f"select * from users", con=create_db_connection())
    users_recommender_model = train_recommender_model(users_df)
    pickle_to_s3(users_recommender_model, key="users_recommender_model")


@repository
def repo():
    assets = assets_from_current_module()
    return [assets, AssetSelection.all().to_job("users_recommender_job")]
