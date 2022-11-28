import numpy as np
import pandas as pd

from colorama import Fore, Style

from taxifare.ml_logic.data import clean_data, get_chunk, save_chunk
from taxifare.ml_logic.model import initialize_model, compile_model, train_model, evaluate_model
from taxifare.ml_logic.params import CHUNK_SIZE, DATASET_SIZE, VALIDATION_DATASET_SIZE
from taxifare.ml_logic.preprocessor import preprocess_features
from taxifare.ml_logic.utils import get_dataset_timestamp
from taxifare.ml_logic.registry import get_model_version

from taxifare.ml_logic.registry import load_model, save_model
import requests


def preprocess_new_data(source_type = 'train'):#experiment
    """
    Run the preprocessing of the new data
    """
    """
    Preprocess the dataset by chunks fitting in memory.
    parameters:
    - source_type: 'train' or 'val'
    """

    print("\n⭐️ Use case: preprocess")

    # Iterate on the dataset, in chunks
    chunk_id = 0
    row_count = 0
    cleaned_row_count = 0
    source_name = f"{source_type}_{DATASET_SIZE}"
    destination_name = f"{source_type}_processed_{DATASET_SIZE}"

    while (True):
        print(Fore.BLUE + f"\nProcessing chunk n°{chunk_id}..." + Style.RESET_ALL)

        data_chunk = get_chunk(
            source_name=source_name,
            index=chunk_id * CHUNK_SIZE,
            chunk_size=CHUNK_SIZE
        )

        # Break out of while loop if data is none
        if data_chunk is None:
            print(Fore.BLUE + "\nNo data in latest chunk..." + Style.RESET_ALL)
            break

        row_count += data_chunk.shape[0]

        data_chunk_cleaned = clean_data(data_chunk)

        cleaned_row_count += len(data_chunk_cleaned)

        # Break out of while loop if cleaning removed all rows
        if len(data_chunk_cleaned) == 0:
            print(Fore.BLUE + "\nNo cleaned data in latest chunk..." + Style.RESET_ALL)
            break

        X_chunk = data_chunk_cleaned.drop("fare_amount", axis=1)
        y_chunk = data_chunk_cleaned[["fare_amount"]]

        X_processed_chunk = preprocess_features(X_chunk)

        data_processed_chunk = pd.DataFrame(
            np.concatenate((X_processed_chunk, y_chunk), axis=1)
        )

        # Save and append the chunk
        is_first = chunk_id == 0

        save_chunk(
            destination_name=destination_name,
            is_first=is_first,
            data=data_processed_chunk
        )

        chunk_id += 1

    if row_count == 0:
        print("\n✅ No new data for the preprocessing 👌")
        return None

    print(f"\n✅ Data processed saved entirely: {row_count} rows ({cleaned_row_count} cleaned)")

    return None

def evaluate_production_model():
    """
    Run the `Production` stage evaluation on new data
    Returns `eval_mae`
    """

    print("\n⭐️ Use case: evaluate")

    # Load new data
    new_data = get_chunk(
        source_name=f"val_processed_{DATASET_SIZE}",
        index=0,
        chunk_size=None
    )  # Retrieve all further data

    if new_data is None:
        print("\n✅ No data to evaluate")
        return None

    new_data = new_data.to_numpy()

    X_new = new_data[:, :-1]
    y_new = new_data[:, -1]

    model = load_model()

    metrics_dict = evaluate_model(model=model, X=X_new, y=y_new)
    mae = metrics_dict["mae"]

    # Save evaluation
    params = dict(
        dataset_timestamp=get_dataset_timestamp(),
        model_version=get_model_version(),

        # Package behavior
        context="evaluate",

        # Data source
        training_set_size=DATASET_SIZE,
        val_set_size=VALIDATION_DATASET_SIZE,
        row_count=len(X_new)
    )

    save_model(params=params, metrics=dict(mae=mae))

    return mae


def re_train(status):
    """
    Run the training
    Returns train_mae
    """
    print("\n⭐️ Use case: train")

    print(Fore.BLUE + "\nLoading preprocessed validation data..." + Style.RESET_ALL)

    # Load a validation set common to all chunks, used to early stop model training
    data_val_processed = get_chunk(
        source_name=f"val_processed_{VALIDATION_DATASET_SIZE}",
        index=0,  # retrieve from first row
        chunk_size=None
    )  # Retrieve all further data

    if data_val_processed is None:
        print("\n✅ no data to train")
        return None

    data_val_processed = data_val_processed.to_numpy()

    X_val_processed = data_val_processed[:, :-1]
    y_val = data_val_processed[:, -1]

    model = None
    model = load_model()  # production model

    # Model params
    learning_rate = 0.001
    batch_size = 256
    patience = 2

    # Iterate on the full dataset per chunks
    chunk_id = 0
    row_count = 0
    metrics_val_list = []

    while (True):

        print(Fore.BLUE + f"\nLoading and training on preprocessed chunk n°{chunk_id}..." + Style.RESET_ALL)

        data_processed_chunk = get_chunk(
            source_name=f"train_processed_{DATASET_SIZE}",
            index=chunk_id * CHUNK_SIZE,
            chunk_size=CHUNK_SIZE
        )

        # Check whether data source contain more data
        if data_processed_chunk is None:
            print(Fore.BLUE + "\nNo more chunk data..." + Style.RESET_ALL)
            break

        data_processed_chunk = data_processed_chunk.to_numpy()

        X_train_chunk = data_processed_chunk[:, :-1]
        y_train_chunk = data_processed_chunk[:, -1]

        # Increment trained row count
        chunk_row_count = data_processed_chunk.shape[0]
        row_count += chunk_row_count

        # Initialize model
        if model is None:
            model = initialize_model(X_train_chunk)

        # (Re-)compile and train the model incrementally
        model = compile_model(model, learning_rate)
        model, history = train_model(
            model,
            X_train_chunk,
            y_train_chunk,
            batch_size=batch_size,
            patience=patience,
            validation_data=(X_val_processed, y_val)
        )

        metrics_val_chunk = np.min(history.history['val_mae'])
        metrics_val_list.append(metrics_val_chunk)
        print(f"Chunk MAE: {round(metrics_val_chunk,2)}")

        # Check if chunk was full
        if chunk_row_count < CHUNK_SIZE:
            print(Fore.BLUE + "\nNo more chunks..." + Style.RESET_ALL)
            break

        chunk_id += 1

    if row_count == 0:
        print("\n✅ no new data for the training 👌")
        return

    # Return the last value of the validation MAE
    val_mae = metrics_val_list[-1]

    print(f"\n✅ trained on {row_count} rows with MAE: {round(val_mae, 2)}")

    params = dict(
        # Model parameters
        learning_rate=learning_rate,
        batch_size=batch_size,
        patience=patience,

        # Package behavior
        context="train",
        chunk_size=CHUNK_SIZE,

        # Data source
        training_set_size=DATASET_SIZE,
        val_set_size=VALIDATION_DATASET_SIZE,
        row_count=row_count,
        model_version=get_model_version(),
        dataset_timestamp=get_dataset_timestamp(),
    )

    # Save model
    save_model(model=model, params=params, metrics=dict(mae=val_mae))

    return val_mae

def notify(eval_mae, train_mae):
    base_url = 'https://wagon-chat.herokuapp.com'
    channel = 'AljokExe' # Change to your batch number when ready

    url = f"{base_url}/{channel}/messages"

    author = 'AljokExe'
    content = "Evaluation MAE: {} - New training MAE: {}".format(
        round(eval_mae, 2), round(train_mae, 2)
    )

    data = dict(author=author, content=content)
    response = requests.post(url, data=data)

    response.raise_for_status()


def build_flow():
    """
    build the prefect workflow for the `taxifare` package
    """
    preprocess_new_data()
    preprocess_new_data(source_type='val')
    train_mae=evaluate_production_model()
    eval_mae=re_train()
    notify(eval_mae, train_mae)
