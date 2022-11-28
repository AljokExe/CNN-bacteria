import os
from prefect import task, Flow, Parameter
# YOUR CODE HERE

def build_parallel_flow():
    """
    build the prefect workflow for the `taxifare` package
    """
    flow_name = os.environ.get("PREFECT_FLOW_NAME")

    with Flow(flow_name) as flow:

        # retrieve mlfow env params
        mlflow_experiment = os.environ.get("MLFLOW_EXPERIMENT")

        # create workflow parameters
        experiment = Parameter(name="experiment", default=mlflow_experiment)

        # register tasks in the workflow
        # YOUR CODE HERE

    return flow
