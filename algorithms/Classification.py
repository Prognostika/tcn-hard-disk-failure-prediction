import os
import pandas as pd
import sys
from sklearn.cluster import DBSCAN
from Dataset_manipulation import *
if not sys.warnoptions:
    import warnings
    warnings.simplefilter("ignore")
from sklearn.ensemble import RandomForestClassifier, IsolationForest, ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.utils import shuffle
from Networks_pytorch import *
from sklearn.metrics import accuracy_score, roc_auc_score, make_scorer, silhouette_score
import torch.optim as optim
from sklearn import svm
from tqdm import tqdm
from xgboost import XGBClassifier
from sklearn.neural_network import MLPClassifier
from datetime import datetime
from joblib import dump
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV, cross_val_score, StratifiedKFold
from sklearn.naive_bayes import GaussianNB
import json
import logger


# Define default global values
TRAINING_PARAMS = {
    'reg': 0.1,
    'batch_size': 256,
    'lr': 0.001,
    'weight_decay': 0.01,
    'epochs': 200,
    'dropout': 0.1,  # LSTM
    'lstm_hidden_s': 64,  # LSTM
    'fc1_hidden_s': 16,  # LSTM
    'hidden_dim': 128,  # MLP_Torch
    'hidden_size': 8,  # DenseNet
    'num_layers': 1,  # NNet
    'optimizer_type': 'Adam',
    'num_workers': 8
}

def save_best_params_to_json(best_params, classifier_name, id_number):
    """
    Saves the best parameters to a JSON file.

    Args:
        best_params (dict): The best parameters.
        classifier_name (str): The name of the classifier.
        id_number (str): The ID number for the model.

    Returns:
        None
    """
    # Define the directory path
    param_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model', id_number)
    # Create the directory if it doesn't exist
    if not os.path.exists(param_dir):
        os.makedirs(param_dir)

    # Define the file path
    file_path = os.path.join(param_dir, f'{classifier_name.lower()}_{id_number}_best_params.json')

    # Save the best parameters to a JSON file
    with open(file_path, 'w') as f:
        json.dump(best_params, f)

    logger.info(f'Best parameters saved to: {file_path}')

def load_best_params_from_json(classifier_name, id_number):
    """
    Loads the best parameters from a JSON file.

    Args:
        classifier_name (str): The name of the classifier.
        id_number (str): The ID number for the model.

    Returns:
        dict: The best parameters.
    """
    # Define the directory path
    param_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model', id_number)

    # Define the file path
    file_path = os.path.join(param_dir, f'{classifier_name.lower()}_{id_number}_best_params.json')

    # Load the best parameters from a JSON file
    with open(file_path, 'r') as f:
        best_params = json.load(f)

    logger.info(f'Best parameters loaded from: {file_path}')

    return best_params

def train_and_evaluate_model(model, param_grid, classifier_name, X_train, Y_train, X_test, Y_test, id_number, metric, search_method='randomized', n_iterations=100):
    """
    Trains and evaluates a machine learning model.

    Args:
        model (object): The machine learning model to be trained and evaluated.
        param_grid (dict): The parameter grid to search over.
        classifier_name (str): The name of the classifier.
        X_train (array-like): The training data features.
        Y_train (array-like): The training data labels.
        X_test (array-like): The test data features.
        Y_test (array-like): The test data labels.
        id_number (str): The ID number for the model.
        metric (str): The metric to be used for evaluation.
        search_method (str, optional): The search method to use. Defaults to 'randomized'.
        n_iterations (int, optional): The number of iterations for training. Defaults to 100.

    Returns:
        str: The path to the saved model file.
    """
    writer = SummaryWriter(f'runs/{classifier_name}_Training_Graph')
    X_train, Y_train = shuffle(X_train, Y_train)

    # Define supervised classifiers
    supervised_classifiers = ['RandomForest', 'KNeighbors', 'DecisionTree', 'LogisticRegression', 'SVM', 'XGB', 'MLP', 'ExtraTrees', 'GradientBoosting', 'NaiveBayes']

    # Define scoring metrics based on the type of classifier
    if classifier_name in supervised_classifiers:
        scoring = {'accuracy': make_scorer(accuracy_score), 'f1': make_scorer(f1_score)}
    else:
        scoring = {'silhouette': make_scorer(silhouette_score)}

    # Choose the search method
    search_method = 'randomized'  # 'grid' for GridSearchCV, 'randomized' for RandomizedSearchCV

    if search_method == 'grid':
        # Initialize GridSearchCV
        search = GridSearchCV(estimator=model, param_grid=param_grid, cv=3, n_jobs=-1, verbose=2, scoring=scoring, refit='f1')
    elif search_method == 'randomized':
        # Initialize RandomizedSearchCV
        search = RandomizedSearchCV(estimator=model, param_distributions=param_grid, cv=3, n_jobs=-1, verbose=2, scoring=scoring, refit='f1', n_iter=100)
    else:
        raise ValueError(f'Invalid search method: {search_method}')

    # Fit the search method
    search.fit(X_train, Y_train)

    if classifier_name in supervised_classifiers:
        # Define StratifiedKFold cross-validator
        stratified_kfold = StratifiedKFold(n_splits=5)
        # Calculate cross validation score
        cv_scores = cross_val_score(search.best_estimator_, X_train, Y_train, cv=stratified_kfold)

        logger.info(f"Cross validation scores: {cv_scores}")
        logger.info(f"Mean cross validation score: {cv_scores.mean()}")
    else:
        # For unsupervised classifiers, calculate silhouette score
        labels = search.best_estimator_.fit_predict(X_train)
        silhouette_avg = silhouette_score(X_train, labels)
        logger.info(f"Silhouette score: {silhouette_avg}")

    # Get the best parameters
    best_params = search.best_params_
    logger.info(f"Best parameters: {best_params}")

    # Save the best parameters to a JSON file
    save_best_params_to_json(best_params, classifier_name, id_number)

    # Get the best estimator
    best_model = search.best_estimator_

    # Split the training data into multiple batches
    batch_size = len(X_train) // n_iterations
    pbar = tqdm(total=n_iterations)  # Initialize tqdm with the total number of batches

    for i in range(0, len(X_train), batch_size):
        best_model.fit(X_train[i:i+batch_size, :], Y_train[i:i+batch_size])
        pbar.update(1)  # Update the progress bar

    pbar.close()
    prediction = best_model.predict(X_test)
    Y_test_real = Y_test
    accuracy = accuracy_score(Y_test_real, prediction)
    auc = roc_auc_score(Y_test_real, prediction)
    logger.info(f'{classifier_name} Prediction Accuracy: {accuracy * 100:.4f}%, AUC: {auc:.2f}')
    report_metrics(Y_test_real, prediction, metric, writer, n_iterations)  # TODO:
    writer.close()

    # Save the trained model to a file
    model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model', id_number)
    # Create the directory if it doesn't exist
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
    # Format as string
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Save the model
    model_path = os.path.join(model_dir, f'{classifier_name}_{id_number}_iterations_{n_iterations}_{now_str}.joblib')
    dump(best_model, model_path)
    logger.info(f'Model saved as: {model_path}')

    return model_path

def classification(X_train, Y_train, X_test, Y_test, classifier, metric, **args):
    """
    Perform classification using the specified classifier.
    --- Step 1.7: Perform Classification
    Parameters:
    - X_train (array-like): Training data features.
    - Y_train (array-like): Training data labels.
    - X_test (array-like): Test data features.
    - Y_test (array-like): Test data labels.
    - classifier (str): The classifier to use. Options: 'RandomForest', 'TCN', 'LSTM'.
    - metric (str): The metric to evaluate the classification performance.
    - **args: Additional arguments specific to each classifier.

    Returns:
    - str: The path to the saved model file.
    """
    logger.info(f'Classification using {classifier} is starting')

    n_iterations = 100
    if classifier == 'RandomForest':
        # Step 1.7.1: Perform Classification using RandomForest.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = RandomForestClassifier(random_state=3, warm_start=True)

        # Define the parameter grid
        param_grid = {
            'n_estimators': [1000, 2000, 3000],
            'min_samples_split': [2, 5, 10],
            'min_samples_leaf': [1, 2, 4],
            'max_features': ['auto', 'sqrt'],
            'max_depth': [10, 20, 30, 40, None],
            'criterion': ['gini', 'entropy'],
            'bootstrap': [True, False]
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'RandomForest', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'KNeighbors':
        # Step 1.7.2: Perform Classification using KNeighbors.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = KNeighborsClassifier()

        # Define the parameter grid
        param_grid = {
            'n_neighbors': list(range(1, 31)),
            'weights': ['uniform', 'distance'],
            'metric': ['euclidean', 'manhattan', 'minkowski']
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'KNeighbors', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'DecisionTree':
        # Step 1.7.3: Perform Classification using DecisionTree.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = DecisionTreeClassifier()

        # Define the parameter grid
        param_grid = {
            'criterion': ['gini', 'entropy'],
            'max_depth': list(range(1, 31)),
            'min_samples_split': [2, 5, 10],
            'min_samples_leaf': [1, 2, 4],
            'max_features': ['auto', 'sqrt', 'log2', None]
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'DecisionTree', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'LogisticRegression':
        # Step 1.7.4: Perform Classification using LogisticRegression.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = LogisticRegression()

        # Define the parameter grid
        param_grid = {
            'penalty': ['l1', 'l2', 'elasticnet', 'none'],
            'C': np.logspace(-4, 4, 20),
            'solver': ['lbfgs', 'newton-cg', 'liblinear', 'sag', 'saga'],
            'max_iter': [100, 1000, 2500, 5000]
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'LogisticRegression', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'SVM':
        # Step 1.7.5: Perform Classification using SVM.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = svm.SVC()

        # Define the parameter grid
        param_grid = {
            'C': [0.1, 1, 10, 100, 1000],  
            'gamma': [1, 0.1, 0.01, 0.001, 0.0001], 
            'kernel': ['linear', 'poly', 'rbf', 'sigmoid']
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'SVM', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'XGB':
        # Step 1.7.7: Perform Classification using XGBoost.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = XGBClassifier()

        # Define the parameter grid
        param_grid = {
            'learning_rate': [0.01, 0.1, 0.2, 0.3],
            'n_estimators': [100, 500, 1000, 1500],
            'max_depth': [3, 5, 7, 9],
            'min_child_weight': [1, 3, 5],
            'gamma': [0.1, 0.2, 0.3, 0.4],
            'subsample': [0.6, 0.8, 1.0],
            'colsample_bytree': [0.6, 0.8, 1.0],
            'objective': ['binary:logistic']
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'XGB', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'IsolationForest':
        # Step 1.7.9: Perform Classification using IsolationForest.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = IsolationForest()

        # Define the parameter grid
        param_grid = {
            'n_estimators': [100, 200, 300, 400, 500],
            'max_samples': ['auto', 100, 200, 300, 400, 500],
            'contamination': ['auto', 0.1, 0.2, 0.3, 0.4, 0.5],
            'max_features': [1, 2, 3, 4, 5],
            'bootstrap': [True, False]
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'IsolationForest', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'ExtraTrees':
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = ExtraTreesClassifier()

        param_grid = {
            'n_estimators': [100, 200, 300, 400, 500],
            'max_features': ['auto', 'sqrt', 'log2'],
            'bootstrap': [True, False]
        }

        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'ExtraTreesClassifier', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'GradientBoosting':
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = GradientBoostingClassifier()

        param_grid = {
            'n_estimators': [100, 200, 300, 400, 500],
            'learning_rate': [0.1, 0.05, 0.01],
            'max_depth': [3, 4, 5, 6, 7],
            'min_samples_split': [2, 5, 10],
            'min_samples_leaf': [1, 2, 5, 10]
        }

        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'GradientBoostingClassifier', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'NaiveBayes':
        # Step 1.7.6: Perform Classification using Naive Bayes.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = GaussianNB()

        # Define the parameter grid
        # Naive Bayes does not have any hyperparameters that need to be tuned
        param_grid = {}

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)

        return train_and_evaluate_model(model, param_grid, 'NaiveBayes', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'TCN':
        # Step 1.7.6: Perform Classification using TCN. Subflowchart: TCN Subflowchart. Train and validate the network using TCN
        # Initialize the TCNTrainer with the appropriate parameters
        tcn_trainer = UnifiedTrainer(
            model=args['net'],                      # The TCN model
            optimizer=args['optimizer'],            # Optimizer for the model
            epochs=args['epochs'],                  # Total number of epochs
            batch_size=args['batch_size'],          # Batch size for training
            lr=args['lr'],                          # Learning rate
            reg=args['reg'],                        # Regularization parameter
            id_number=args['id_number'],
            model_type='TCN',
            num_workers=args['num_workers']
        )
        # Run training and testing using the TCNTrainer
        return tcn_trainer.run(X_train, Y_train, X_test, Y_test)
    elif classifier == 'LSTM':
        # Step 1.7.7: Perform Classification using LSTM. Subflowchart: LSTM Subflowchart. Train and validate the network using LSTM
        lstm_trainer = UnifiedTrainer(
            model=args['net'],                      # The MLP model
            optimizer=args['optimizer'],            # Optimizer for the model
            epochs=args['epochs'],                  # Total number of epochs
            batch_size=args['batch_size'],          # Batch size for training
            lr=args['lr'],                          # Learning rate
            reg=args['reg'],                        # Regularization parameter
            id_number=args['id_number'],
            model_type='LSTM',
            num_workers=args['num_workers']
        )
        # Run training and testing using the TCNTrainer
        return lstm_trainer.run(X_train, Y_train, X_test, Y_test)
    elif classifier == 'NNet':
        # Step 1.7.7: Perform Classification using LSTM. Subflowchart: LSTM Subflowchart. Train and validate the network using LSTM
        nnet_trainer = UnifiedTrainer(
            model=args['net'],                      # The MLP model
            optimizer=args['optimizer'],            # Optimizer for the model
            epochs=args['epochs'],                  # Total number of epochs
            batch_size=args['batch_size'],          # Batch size for training
            lr=args['lr'],                          # Learning rate
            reg=args['reg'],                        # Regularization parameter
            id_number=args['id_number'],
            model_type='NNet',
            num_workers=args['num_workers']
        )
        # Run training and testing using the TCNTrainer
        return nnet_trainer.run(X_train, Y_train, X_test, Y_test)
    elif classifier == 'DenseNet':
        # Step 1.7.7: Perform Classification using LSTM. Subflowchart: LSTM Subflowchart. Train and validate the network using LSTM
        densenet_trainer = UnifiedTrainer(
            model=args['net'],                      # The MLP model
            optimizer=args['optimizer'],            # Optimizer for the model
            epochs=args['epochs'],                  # Total number of epochs
            batch_size=args['batch_size'],          # Batch size for training
            lr=args['lr'],                          # Learning rate
            reg=args['reg'],                        # Regularization parameter
            id_number=args['id_number'],
            model_type='DenseNet',
            num_workers=args['num_workers']
        )
        # Run training and testing using the TCNTrainer
        return densenet_trainer.run(X_train, Y_train, X_test, Y_test)
    elif classifier == 'MLP_Torch':
        # Step 1.7.8: Perform Classification using MLP. Subflowchart: MLP Subflowchart. Train and validate the network using MLP
        # Initialize the MLPTrainer with the appropriate parameters
        mlp_trainer = UnifiedTrainer(
            model=args['net'],                      # The MLP model
            optimizer=args['optimizer'],            # Optimizer for the model
            epochs=args['epochs'],                  # Total number of epochs
            batch_size=args['batch_size'],          # Batch size for training
            lr=args['lr'],                          # Learning rate
            reg=args['reg'],                        # Regularization parameter
            id_number=args['id_number'],
            model_type='MLP',
            num_workers=args['num_workers']
        )
        # Run training and testing using the MLPTrainer
        return mlp_trainer.run(X_train, Y_train, X_test, Y_test)
    elif classifier == 'MLP':
        # Step 1.7.8: Perform Classification using MLP.
        model = MLPClassifier()
        
        # Define the parameter grid
        param_grid = {
            'hidden_layer_sizes': [(50,50,50), (50,100,50), (100,)],
            'activation': ['tanh', 'relu'],
            'solver': ['sgd', 'adam'],
            'alpha': [0.0001, 0.05],
            'learning_rate': ['constant','adaptive'],
            'max_iter': [200, 500, 1000]
        }

        return train_and_evaluate_model(model, param_grid, 'MLP', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)
    elif classifier == 'DBSCAN':
        # Step 1.7.3: Perform Classification using DBSCAN.
        try:
            best_params = load_best_params_from_json(classifier, args['id_number'])
        except FileNotFoundError:
            best_params = None

        model = DBSCAN()

        # Define the parameter grid
        param_grid = {
            'eps': [0.3, 0.5, 0.7],
            'min_samples': [5, 10, 15],
            'leaf_size': [10, 20, 30],
            'metric': ['euclidean', 'manhattan', 'chebyshev']
        }

        # If the best parameters exist, use them
        if best_params:
            model.set_params(**best_params)
            param_grid = {}

        return train_and_evaluate_model(model, param_grid, 'DBSCAN', X_train, Y_train, X_test, Y_test, args['id_number'], metric, args['search_method'], n_iterations)

def factors(n):
    """
    Returns a list of factors of the given number.

    Parameters:
    - n (int): The number to find the factors of.

    Returns:
    list: A list of factors of the given number.
    """
    factors = []
    # Check for the smallest prime factor 2
    while n % 2 == 0:
        factors.append(2)
        n //= 2
    # Check for odd factors from 3 upwards
    factor = 3
    while factor * factor <= n:
        while n % factor == 0:
            factors.append(factor)
            n //= factor
        factor += 2
    # If n became a prime number greater than 2
    if n > 1:
        factors.append(n)
    return factors

def save_params_to_json(df, *args):
    """
    Save the parameters to a JSON file.

    Args:
        df (DataFrame): The input DataFrame.
        *args: Variable length argument list containing the parameter values.

    Returns:
        str: The file path where the parameters are saved.
    """
    # Define parameter names and create a dictionary of params
    param_names = [
        'model', 'id_number', 'years', 'test_type','windowing', 'min_days_hdd', 'days_considered_as_failure',
        'test_train_percentage', 'oversample_undersample', 'balancing_normal_failed',
        'history_signal', 'classifier', 'features_extraction_method', 'cuda_dev',
        'ranking', 'num_features', 'overlap', 'split_technique', 'interpolate_technique',
        'search_method', 'fillna_method', 'pca_components'
    ]

    # Assign values directly from the dictionary
    params = dict(zip(param_names, args))

    # Get column names that start with 'smart_'
    smart_columns = [col for col in df.columns if col.startswith('smart_')]

    # Add smart_columns to params under the key 'smart_attributes'
    params['smart_attributes'] = smart_columns

    script_dir = os.path.dirname(os.path.abspath(__file__))
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    param_dir = os.path.join(script_dir, '..', 'model', params['id_number'])

    # Create the directory if it doesn't exist
    if not os.path.exists(param_dir):
        os.makedirs(param_dir)

    logger.info(f'User parameters: {params}')

    # Define the file path
    file_path = os.path.join(param_dir, f"{params['classifier'].lower()}_{params['id_number']}_params_{now_str}.json")

    # Write the params dictionary to a JSON file
    with open(file_path, 'w') as f:
        json.dump(params, f)

    logger.info(f'Parameters saved to: {file_path}')

    return file_path

def set_training_params(*args):
    param_names = ['reg', 'batch_size', 'lr', 'weight_decay', 'epochs', 'dropout', 'lstm_hidden_s', 'fc1_hidden_s', 'hidden_dim', 'hidden_size', 'num_layers', 'optimizer_type', 'num_workers']
    # Use the global keyword when modifying global variables
    global TRAINING_PARAMS
    TRAINING_PARAMS = dict(zip(param_names, args))
    # Print out updated parameters to Gradio interface
    return f"Parameters successfully updated:\n" + "\n".join([f"{key}: {value}" for key, value in TRAINING_PARAMS.items()])

def initialize_classification(*args):
    # ------------------ #
    # Feature Selection Subflowchart
    # Step 1: Define empty lists and dictionary
    features = {
        'total_features': [
            'date',
            'serial_number',
            'model',
            'failure',
            'smart_1_normalized', 
            'smart_5_normalized',
            'smart_5_raw',
            'smart_7_normalized',
            'smart_9_raw',
            'smart_12_raw',
            'smart_183_raw',
            'smart_184_normalized',
            'smart_184_raw',
            'smart_187_normalized',
            'smart_187_raw',
            'smart_189_normalized', 
            'smart_193_normalized',
            'smart_193_raw',
            'smart_197_normalized', 
            'smart_197_raw',
            'smart_198_normalized',
            'smart_198_raw',
            'smart_199_raw'
        ],
        'iSTEP': [
            'date',
            'serial_number',
            'model',
            'failure',
            'smart_5_raw',
            'smart_3_raw',
            'smart_10_raw',
            'smart_12_raw',
            'smart_4_raw',
            'smart_194_raw',
            'smart_1_raw',
            'smart_9_raw',
            'smart_192_raw',
            'smart_193_raw',
            'smart_197_raw',
            'smart_198_raw',
            'smart_199_raw'
        ]
    }
    
    # Define parameter names and create a dictionary of params
    param_names = [
        'model', 'id_number', 'years', 'test_type', 'windowing', 'min_days_hdd', 'days_considered_as_failure',
        'test_train_percentage', 'oversample_undersample', 'balancing_normal_failed',
        'history_signal', 'classifier', 'features_extraction_method', 'cuda_dev',
        'ranking', 'num_features', 'overlap', 'split_technique', 'interpolate_technique',
        'search_method', 'fillna_method', 'pca_components'
    ]

    # Assign values directly from the dictionary
    (
        model, id_number, years, test_type, windowing, min_days_HDD, days_considered_as_failure,
        test_train_perc, oversample_undersample, balancing_normal_failed,
        history_signal, classifier, features_extraction_method, CUDA_DEV,
        ranking, num_features, overlap, split_technique, interpolate_technique,
        search_method, fillna_method, pca_components
    ) = dict(zip(param_names, args)).values()
    # here you can select the model. This is the one tested.
    # Correct years for the model
    # Select the statistical methods to extract features
    # many parameters that could be changed, both for unbalancing, for networks and for features.
    # minimum number of days for a HDD to be filtered out
    # Days considered as failure
    # percentage of the test set
    # type of oversampling: 0 means undersample, 1 means oversample, 2 means no balancing technique applied
    # The balance factor (major/minor = balancing_normal_failed) is used to balance the number of normal and failed samples in the dataset, default as 'auto'
    # length of the window
    # type of classifier
    # if you extract features for RF for example. Not tested
    # cuda device
    # if automatically select best features
    # number of SMART features to select
    # overlap option of the window
    # split technique for dataset partitioning
    # interpolation technique for the rows with missing dates

    try:
        # Try to convert to float
        balancing_normal_failed = float(balancing_normal_failed)
    except ValueError:
        # If it fails, it's a string and we leave it as is
        pass

    logger.info(f'Logger initialized successfully! Current id number is: {id_number}')

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, '..', 'output')
    # Create the directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        # Step 1: Load the dataset from pkl file.
        df = pd.read_pickle(os.path.join(script_dir, '..', 'output', f'{model}_Dataset_selected_windowed_{history_signal}_rank_{ranking}_{num_features}_overlap_{overlap}.pkl'))
    except:
        # Step 1.1: Import the dataset from the raw data.
        if ranking == 'None':
            df = import_data(years=years, model=model, name='iSTEP', features=features)
        else:
            df = import_data(years=years, model=model, name='iSTEP')

        logger.info('Data imported successfully, processing smart attributes...')
        for column in list(df):
            missing = round(df[column].notna().sum() / df.shape[0] * 100, 2)
            logger.info(f"{column:<27}.{missing}%")
        # Step 1.2: Filter out the bad HDDs.
        bad_missing_hds, bad_power_hds, df = filter_HDs_out(df, min_days=min_days_HDD, time_window='30D', tolerance=2)
        # predict_val represents the prediction value of the failure
        # validate_val represents the validation value of the failure
        # Step 1.3: Define RUL(Remain useful life) Piecewise
        df, pred_list, valid_list = generate_failure_predictions(df, days=days_considered_as_failure, window=history_signal)

        # Create a new DataFrame with the results since the previous function may filter out some groups from the DataFrame
        df['predict_val'] = pred_list
        df['validate_val'] = valid_list

        if ranking != 'None':
            # Step 1.4: Feature Selection: Subflow chart of Main Classification Process
            df = feature_selection(df, num_features, test_type)
        logger.info('Used features')
        for column in list(df):
            logger.info(f'{column:<27}.')
        logger.info(f'Saving to pickle file: {model}_Dataset_selected_windowed_{history_signal}_rank_{ranking}_{num_features}_overlap_{overlap}.pkl')
        df.to_pickle(os.path.join(output_dir, f'{model}_Dataset_selected_windowed_{history_signal}_rank_{ranking}_{num_features}_overlap_{overlap}.pkl'))

    # Interpolate data for the rows with missing dates
    if interpolate_technique != 'None':
        df = interpolate_ts(df, method=interpolate_technique)

    # Saving parameters to json file
    logger.info('Saving parameters to json file...')
    param_path = save_params_to_json(
        df, model, id_number, years, test_type, windowing, min_days_HDD, days_considered_as_failure,
        test_train_perc, oversample_undersample, balancing_normal_failed,
        history_signal, classifier, features_extraction_method, CUDA_DEV,
        ranking, num_features, overlap, split_technique, interpolate_technique,
        search_method, fillna_method, pca_components
    )

    ## -------- ##
    # random: stratified without keeping time order
    # hdd --> separate different hdd (need FIXes)
    # temporal --> separate by time (need FIXes)
    # Step 1.5: Partition the dataset into training and testing sets. Partition Dataset: Subflow chart of Main Classification Process
    Xtrain, Xtest, ytrain, ytest = DatasetPartitioner(
        df,
        model,
        overlap=overlap,
        rank=ranking,
        num_features=num_features,
        technique=split_technique,
        test_train_perc=test_train_perc,
        windowing=windowing,
        window_dim=history_signal,
        resampler_balancing=balancing_normal_failed,
        oversample_undersample=oversample_undersample,
        fillna_method=fillna_method
    )
    
    # Print the line of Xtrain and Xtest
    logger.info(f'Xtrain shape: {Xtrain.shape}, Xtest shape: {Xtest.shape}')

    try:
        data = np.load(os.path.join(output_dir, f'{model}_training_and_testing_data_{history_signal}_rank_{ranking}_{num_features}_overlap_{overlap}_features_extraction_method_{features_extraction_method}_oversample_undersample_{oversample_undersample}.npz'))
        Xtrain, Xtest, ytrain, ytest = data['Xtrain'], data['Xtest'], data['Ytrain'], data['Ytest']
    except:
        # Step x.1: Feature Extraction
        if features_extraction_method == 'custom':
            # Extract features for the train and test set
            Xtrain = feature_extraction(Xtrain)
            Xtest = feature_extraction(Xtest)
        elif features_extraction_method == 'PCA':
            Xtrain = feature_extraction_PCA(Xtrain, pca_components)
            Xtest = feature_extraction_PCA(Xtest, pca_components)
        elif features_extraction_method == 'None':
            logger.info('Skipping features extraction for training data.')
        else:
            raise ValueError('Invalid features extraction method. Please choose either "custom" or "pca" or "None".')
        # Save the arrays to a .npz file
        np.savez(os.path.join(output_dir, f'{model}_training_and_testing_data_{history_signal}_rank_{ranking}_{num_features}_overlap_{overlap}_features_extraction_method_{features_extraction_method}_oversample_undersample_{oversample_undersample}.npz'), Xtrain=Xtrain, Xtest=Xtest, Ytrain=ytrain, Ytest=ytest)

    # Step 1.6: Classifier Selection: set training parameters
    ####### CLASSIFIER PARAMETERS #######
    if CUDA_DEV != 'None':
        os.environ["CUDA_VISIBLE_DEVICES"] = CUDA_DEV
    if classifier == 'TCN':
        # Step 1.6.1: Set training parameters for TCN. Subflowchart: TCN Subflowchart.
        batch_size = TRAINING_PARAMS['batch_size']
        lr = TRAINING_PARAMS['lr']
        weight_decay = TRAINING_PARAMS['weight_decay']  # L2 regularization parameter
        epochs = TRAINING_PARAMS['epochs']
        optimizer_type = TRAINING_PARAMS['optimizer_type']
        reg = TRAINING_PARAMS['reg']
        num_workers = TRAINING_PARAMS['num_workers']
        # Calculate the data dimension based on the shape of the training data, the dimension of the Xtrain is the same as Xtest
        data_dim = Xtrain.shape[2]
        num_inputs = Xtrain.shape[1]
        logger.info(f'number of inputes: {num_inputs}, data_dim: {data_dim}')
        net = TCN_Network(data_dim, num_inputs)
        if torch.cuda.is_available():
            logger.info('Moving model to cuda')
            net.cuda()
        else:
            logger.info('Model to cpu')
        if optimizer_type == 'Adam':
            # We use the Adam optimizer, a method for Stochastic Optimization
            optimizer = optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
        elif optimizer_type == 'SGD':
            # We use the Stochastic Gradient Descent optimizer
            optimizer = optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay)
        else:
            raise ValueError('Invalid optimizer type. Please choose either "Adam" or "SGD".')

        # Define the best parameters
        best_params = {
            'batch_size': batch_size,
            'lr': lr,
            'weight_decay': weight_decay,
            'epochs': epochs,
            'reg': reg,
        }

        # Save the best parameters to a JSON file
        save_best_params_to_json(best_params, classifier, id_number)
    elif classifier == 'LSTM':
        # Step 1.6.2: Set training parameters for LSTM. Subflowchart: LSTM Subflowchart.
        lr = TRAINING_PARAMS['lr']
        weight_decay = TRAINING_PARAMS['weight_decay']  # L2 regularization parameter
        batch_size = TRAINING_PARAMS['batch_size']
        epochs = TRAINING_PARAMS['epochs']
        dropout = TRAINING_PARAMS['dropout']
        # Hidden state sizes (from [14])
        # The dimensionality of the output space of the LSTM layer
        lstm_hidden_s = TRAINING_PARAMS['lstm_hidden_s']
        # The dimensionality of the output space of the first fully connected layer
        fc1_hidden_s = TRAINING_PARAMS['fc1_hidden_s']
        optimizer_type = TRAINING_PARAMS['optimizer_type']
        reg = TRAINING_PARAMS['reg']
        num_workers = TRAINING_PARAMS['num_workers']
        num_inputs = Xtrain.shape[1]
        net = FPLSTM(lstm_hidden_s, fc1_hidden_s, num_inputs, 2, dropout)
        if torch.cuda.is_available():
            logger.info('Moving model to cuda')
            net.cuda()
        else:
            logger.info('Model to cpu')
        if optimizer_type == 'Adam':
            # We use the Adam optimizer, a method for Stochastic Optimization
            optimizer = optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
        elif optimizer_type == 'SGD':
            # We use the Stochastic Gradient Descent optimizer
            optimizer = optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay)
        else:
            raise ValueError('Invalid optimizer type. Please choose either "Adam" or "SGD".')

        # Define the best parameters
        best_params = {
            'batch_size': batch_size,
            'lr': lr,
            'weight_decay': weight_decay,
            'epochs': epochs,
            'dropout': dropout,
            'lstm_hidden_s': lstm_hidden_s,
            'fc1_hidden_s': fc1_hidden_s,
            'reg': reg,
        }

        # Save the best parameters to a JSON file
        save_best_params_to_json(best_params, classifier, id_number)
    elif classifier == 'MLP_Torch':
        # Step 1.6.4: Set training parameters for MLP. Subflowchart: MLP Subflowchart.
        batch_size = TRAINING_PARAMS['batch_size']
        lr = TRAINING_PARAMS['lr']
        weight_decay = TRAINING_PARAMS['weight_decay']  # L2 regularization parameter
        epochs = TRAINING_PARAMS['epochs']
        input_dim = Xtrain.shape[1] * Xtrain.shape[2]  # Number of features in the input (5*32)
        hidden_dim = TRAINING_PARAMS['hidden_dim']  # Example hidden dimension, can be adjusted
        optimizer_type = TRAINING_PARAMS['optimizer_type']
        reg = TRAINING_PARAMS['reg']
        num_workers = TRAINING_PARAMS['num_workers']
        logger.info(f'number of inputs: {input_dim}, hidden_dim: {hidden_dim}')
        net = MLP(input_dim=input_dim, hidden_dim=hidden_dim)
        if torch.cuda.is_available():
            logger.info('Moving model to cuda')
            net.cuda()
        else:
            logger.info('Model to cpu')
        if optimizer_type == 'Adam':
            # We use the Adam optimizer, a method for Stochastic Optimization
            optimizer = optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
        elif optimizer_type == 'SGD':
            # We use the Stochastic Gradient Descent optimizer
            optimizer = optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay)
        else:
            raise ValueError('Invalid optimizer type. Please choose either "Adam" or "SGD".')

        # Define the best parameters
        best_params = {
            'batch_size': batch_size,
            'lr': lr,
            'weight_decay': weight_decay,
            'epochs': epochs,
            'hidden_dim': hidden_dim,
            'reg': reg,
        }

        # Save the best parameters to a JSON file
        save_best_params_to_json(best_params, classifier, id_number)
    elif classifier == 'NNet':
        # Step 1.6.4: Set training parameters for MLP. Subflowchart: MLP Subflowchart.
        batch_size = TRAINING_PARAMS['batch_size']
        lr = TRAINING_PARAMS['lr']
        weight_decay = TRAINING_PARAMS['weight_decay']  # L2 regularization parameter
        epochs = TRAINING_PARAMS['epochs']
        dropout = TRAINING_PARAMS['dropout']
        hidden_dim = TRAINING_PARAMS['hidden_dim']  # Example hidden dimension, can be adjusted
        num_layers = TRAINING_PARAMS['num_layers']
        optimizer_type = TRAINING_PARAMS['optimizer_type']
        reg = TRAINING_PARAMS['reg']
        num_workers = TRAINING_PARAMS['num_workers']
        num_inputs = Xtrain.shape[2]  # Number of features in the input (32)
        logger.info(f'number of inputs: {num_inputs}, hidden_dim: {hidden_dim}')
        net = NNet(input_size=num_inputs, hidden_dim=hidden_dim, num_layers=num_layers, dropout=dropout)
        if torch.cuda.is_available():
            logger.info('Moving model to cuda')
            net.cuda()
        else:
            logger.info('Model to cpu')
        if optimizer_type == 'Adam':
            # We use the Adam optimizer, a method for Stochastic Optimization
            optimizer = optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
        elif optimizer_type == 'SGD':
            # We use the Stochastic Gradient Descent optimizer
            optimizer = optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay)
        else:
            raise ValueError('Invalid optimizer type. Please choose either "Adam" or "SGD".')

        # Define the best parameters
        best_params = {
            'batch_size': batch_size,
            'lr': lr,
            'weight_decay': weight_decay,
            'epochs': epochs,
            'hidden_dim': hidden_dim,
            'num_layers': num_layers,
            'reg': reg,
        }

        # Save the best parameters to a JSON file
        save_best_params_to_json(best_params, classifier, id_number)
    elif classifier == 'DenseNet':
        # Step 1.6.4: Set training parameters for MLP. Subflowchart: MLP Subflowchart.
        batch_size = TRAINING_PARAMS['batch_size']
        lr = TRAINING_PARAMS['lr']
        weight_decay = TRAINING_PARAMS['weight_decay']  # L2 regularization parameter
        epochs = TRAINING_PARAMS['epochs']
        hidden_size = TRAINING_PARAMS['hidden_size']  # Example hidden dimension, can be adjusted
        optimizer_type = TRAINING_PARAMS['optimizer_type']
        reg = TRAINING_PARAMS['reg']
        num_workers = TRAINING_PARAMS['num_workers']
        num_inputs = Xtrain.shape[1]
        logger.info(f'number of inputs: {num_inputs}, hidden_size: {hidden_size} x {hidden_size}')
        net = DenseNet(input_size=num_inputs, hidden_size=hidden_size)
        if torch.cuda.is_available():
            logger.info('Moving model to cuda')
            net.cuda()
        else:
            logger.info('Model to cpu')
        if optimizer_type == 'Adam':
            # We use the Adam optimizer, a method for Stochastic Optimization
            optimizer = optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
        elif optimizer_type == 'SGD':
            # We use the Stochastic Gradient Descent optimizer
            optimizer = optim.SGD(net.parameters(), lr=lr, weight_decay=weight_decay)
        else:
            raise ValueError('Invalid optimizer type. Please choose either "Adam" or "SGD".')

        # Define the best parameters
        best_params = {
            'batch_size': batch_size,
            'lr': lr,
            'weight_decay': weight_decay,
            'epochs': epochs,
            'hidden_size': hidden_size,
            'num_layers': num_layers,
            'reg': reg,
        }

        # Save the best parameters to a JSON file
        save_best_params_to_json(best_params, classifier, id_number)
    ## ---------------------------- ##
    # Step x.2: Reshape the data for RandomForest: We jumped from Step 1.6.1, use third-party RandomForest library
    classifiers = [
        'RandomForest', 
        'KNeighbors', 
        'DecisionTree', 
        'LogisticRegression', 
        'SVM', 
        'XGB', 
        'MLP', 
        'IsolationForest', 
        'ExtraTrees', 
        'GradientBoosting', 
        'NaiveBayes', 
        'DBSCAN'
    ]
    if classifier in classifiers and windowing == 1:
        Xtrain = Xtrain.reshape(Xtrain.shape[0], Xtrain.shape[1] * Xtrain.shape[2])
        Xtest = Xtest.reshape(Xtest.shape[0], Xtest.shape[1] * Xtest.shape[2])

    try:
        # Parameters for TCN and LSTM networks
        model_path = classification(
            X_train=Xtrain,
            Y_train=ytrain,
            X_test=Xtest,
            Y_test=ytest,
            classifier=classifier,
            metric=['RMSE', 'MAE', 'FDR', 'FAR', 'F1', 'recall', 'precision'],
            net=net,
            optimizer=optimizer,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
            reg=reg,
            id_number=id_number,
            num_workers=num_workers
        )
    except:
        # Parameters for RandomForest
        model_path = classification(
            X_train=Xtrain,
            Y_train=ytrain,
            X_test=Xtest,
            Y_test=ytest,
            classifier=classifier,
            # FDR, FAR, F1, recall, precision are not calculated for some algorithms, it will report as 0.0
            metric=['RMSE', 'MAE', 'FDR', 'FAR', 'F1', 'recall', 'precision'],
            search_method=search_method,
            id_number=id_number
        )

    return logger.get_log_file_path(), model_path, param_path