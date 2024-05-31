import torch.nn.functional as F
from torch import nn
import torch
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error, f1_score, recall_score, precision_score, accuracy_score, roc_auc_score, log_loss
from sklearn.utils import shuffle
import math
from collections import deque
from torch.utils.tensorboard import SummaryWriter
from datetime import datetime
import os


# these 2 functions are used to rightly convert the dataset for LSTM prediction
class FPLSTMDataset(torch.utils.data.Dataset):
    """
    A PyTorch dataset class for the FPLSTM model.

    Args:
        x (numpy.ndarray): Input data of shape (num_samples, num_timesteps, num_features).
        y (numpy.ndarray): Target labels of shape (num_samples,).

    Attributes:
        x_tensors (dict): Dictionary containing input data tensors, with keys as indices and values as torch.Tensor objects.
        y_tensors (dict): Dictionary containing target label tensors, with keys as indices and values as torch.Tensor objects.
    """

    def __init__(self, x, y):
        # swap axes to have timesteps before features
        self.x_tensors = {i : torch.as_tensor(np.swapaxes(x[i,:,:], 0, 1),
            dtype=torch.float32) for i in range(x.shape[0])}
        self.y_tensors = {i : torch.as_tensor(y[i], dtype=torch.int64)
                for i in range(y.shape[0])}

    def __len__(self):
        """
        Returns the number of samples in the dataset.

        Returns:
            int: Number of samples.
        """
        return len(self.x_tensors.keys())

    def __getitem__(self, idx):
        """
        Returns the data and label at the given index.

        Args:
            idx (int): Index of the sample.

        Returns:
            tuple: A tuple containing the input data tensor and the target label tensor.
        """
        return (self.x_tensors[idx], self.y_tensors[idx])

# fault prediction LSTM: this network is used as a reference in the paper
class FPLSTM(nn.Module):

    def __init__(self, lstm_size, fc1_size, input_size, n_classes, dropout_prob):
        """
        Initialize the FPLSTM class.

        Args:
            lstm_size (int): The size of the LSTM layer.
            fc1_size (int): The size of the first fully connected layer.
            input_size (int): The size of the input.
            n_classes (int): The number of output classes.
            dropout_prob (float): The probability of dropout.

        Returns:
            None
        """
        super(FPLSTM, self).__init__()
        # The model layers include:
        # - LSTM: Processes the input sequence with a specified number of features in the hidden state.
        # - Dropout1: Applies dropout after the LSTM to reduce overfitting.
        # - FC1: A fully connected layer that maps the LSTM output to a higher or lower dimensional space.
        # - Dropout2: Applies dropout after the first fully connected layer.
        # - FC2: The final fully connected layer that outputs the predictions for the given number of classes.
        self.lstm_size = lstm_size
        self.lstm = nn.LSTM(input_size, lstm_size)
        self.do1 = nn.Dropout(dropout_prob)
        self.fc1 = nn.Linear(lstm_size, fc1_size)
        self.do2 = nn.Dropout(dropout_prob)
        self.fc2 = nn.Linear(fc1_size, n_classes)

    def forward(self, x_batch):
        """
        Forward pass of the network.

        Args:
            x_batch (torch.Tensor): Input batch of data.

        Returns:
            torch.Tensor: Output of the network.
        """
        _, last_lstm_out = self.lstm(x_batch)
        (h_last, c_last) = last_lstm_out
        # reshape to (batch_size, hidden_size)
        h_last = h_last[-1]
        do1_out = self.do1(h_last)
        fc1_out = F.relu(self.fc1(do1_out))
        do2_out = self.do2(fc1_out)
        # fc2_out = F.log_softmax(self.fc2(do2_out), dim=1)
        fc2_out = self.fc2(do2_out)
        return fc2_out

class MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim):
        """
        Initialize the MLP class.

        Args:
            input_dim (int): The input dimension of the MLP.
            hidden_dim (int): The hidden dimension of the MLP.
        """
        super(MLP, self).__init__()
        # The model layers include:
        # - Linear1: A fully connected layer that maps the input to the hidden dimension.
        # - ReLU: Applies the ReLU activation function to the output of the first fully connected layer.
        # - Linear2: A fully connected layer that maps the hidden dimension to the output dimension.
        # - ReLU: Applies the ReLU activation function to the output of the second fully connected layer.
        # - Linear3: A fully connected layer that maps the output dimension to the number of classes.
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        # Define the layers
        self.lin1 = nn.Linear(self.input_dim, self.hidden_dim)
        self.lin2 = nn.Linear(self.hidden_dim, self.hidden_dim)
        self.lin3 = nn.Linear(self.hidden_dim, 2)

    def forward(self, input):
        """
        Performs the forward pass of the network.

        Args:
            input (torch.Tensor): The input tensor.

        Returns:
            torch.Tensor: The output tensor.
        """
        flattened_input = input.view(input.shape[0], -1).float()  # Ensure data is flattened
        hidden_layer1_output = F.relu(self.lin1(flattened_input))
        hidden_layer2_output = F.relu(self.lin2(hidden_layer1_output))
        final_output = self.lin3(hidden_layer2_output)
        return final_output

## this is the network used in the paper. It is a 1D conv with dilation
class TCN_Network(nn.Module):
    
    def __init__(self, history_signal, num_inputs):
        """
        Initializes the TCN_Network class.

        Args:
            history_signal (int): The length of the input signal history.
            num_inputs (int): The number of input features.

        """
        super(TCN_Network, self).__init__()

        # Dilated Convolution Block 0: 
        # - 1D Convolutional layer (Conv1d) with num_inputs input channels, 32 output channels, kernel size of 3, dilation of 2, and padding of 2.
        # - Batch normalization (BatchNorm1d) for 32 features.
        # - ReLU activation function.
        # - Second 1D Convolutional layer (Conv1d) with 32 input channels, 64 output channels, kernel size of 3, dilation of 2, and padding of 2.
        # - 1D Average pooling layer (AvgPool1d) with kernel size of 3, stride of 2, and padding of 1.
        # - Batch normalization (BatchNorm1d) for 64 features.
        # - ReLU activation function.
        self.b0_tcn0 = nn.Conv1d(num_inputs, 32, 3, dilation=2, padding=2)
        self.b0_tcn0_BN = nn.BatchNorm1d(32)
        self.b0_tcn0_ReLU = nn.ReLU()
        self.b0_tcn1 = nn.Conv1d(32, 64, 3, dilation=2, padding=2)
        self.b0_conv_pool = torch.nn.AvgPool1d(3, stride=2, padding=1)
        self.b0_tcn1_BN = nn.BatchNorm1d(64)
        self.b0_tcn1_ReLU = nn.ReLU()

        # Dilated Convolution Block 1:
        # - 1D Convolutional layer (Conv1d) with 64 input channels, 64 output channels, kernel size of 3, dilation of 2, and padding of 2.
        # - Batch normalization (BatchNorm1d) for 64 features.
        # - ReLU activation function.
        # - Second 1D Convolutional layer (Conv1d) with 64 input channels, 128 output channels, kernel size of 3, dilation of 2, and padding of 2.
        # - 1D Average pooling layer (AvgPool1d) with kernel size of 3, stride of 2, and padding of 1.
        # - Batch normalization (BatchNorm1d) for 128 features.
        # - ReLU activation function.
        self.b1_tcn0 = nn.Conv1d(64, 64, 3, dilation=2, padding=2)
        self.b1_tcn0_BN = nn.BatchNorm1d(64)
        self.b1_tcn0_ReLU = nn.ReLU()
        self.b1_tcn1 = nn.Conv1d(64, 128, 3, dilation=2, padding=2)
        self.b1_conv_pool = torch.nn.AvgPool1d(3, stride=2, padding=1)
        self.b1_tcn1_BN = nn.BatchNorm1d(128)
        self.b1_tcn1_ReLU = nn.ReLU()

        # Dilated Convolution Block 2:
        # - 1D Convolutional layer (Conv1d) with 128 input channels, 128 output channels, kernel size of 3, dilation of 4, and padding of 4.
        # - Batch normalization (BatchNorm1d) for 128 features.
        # - ReLU activation function.
        # - Repeat 1D Convolutional layer with the same specifications as the first.
        # - 1D Average pooling layer (AvgPool1d) with kernel size of 3, stride of 2, and padding of 1.
        # - Batch normalization (BatchNorm1d) for 128 features from the second convolutional layer.
        # - ReLU activation function.
        self.b2_tcn0 = nn.Conv1d(128, 128, 3, dilation=4, padding=4)
        self.b2_tcn0_BN = nn.BatchNorm1d(128)
        self.b2_tcn0_ReLU = nn.ReLU()
        self.b2_tcn1 = nn.Conv1d(128, 128, 3, dilation=4, padding=4)
        self.b2_conv_pool = torch.nn.AvgPool1d(3, stride=2, padding=1)
        self.b2_tcn1_BN = nn.BatchNorm1d(128)
        self.b2_tcn1_ReLU = nn.ReLU()

        # Fully Connected Layer 0:
        # - FC0: Linear transformation from dynamically calculated dimension (based on signal history and pooling) to 256 units. Calculated as the ceiling of three halvings of history_signal multiplied by 128.
        # - Batch normalization (BatchNorm1d) for 256 features.
        # - ReLU activation function.
        # - Dropout applied at 50% rate to reduce overfitting.

        dim_fc = int(math.ceil(math.ceil(math.ceil(history_signal/2)/2)/2)*128)
        self.FC0 = nn.Linear(dim_fc, 256) # 592 in the Excel, 768 ours with pooling
        self.FC0_BN = nn.BatchNorm1d(256)
        self.FC0_ReLU = nn.ReLU()
        self.FC0_dropout = nn.Dropout(0.5)

        # Fully Connected Layer 1:
        # - FC1: Linear transformation from 256 to 64 units.
        # - Batch normalization (BatchNorm1d) for 64 features.
        # - ReLU activation function.
        # - Dropout applied at 50% rate.
        self.FC1 = nn.Linear(256, 64)
        self.FC1_BN = nn.BatchNorm1d(64)
        self.FC1_ReLU = nn.ReLU()
        self.FC1_dropout = nn.Dropout(0.5)
        
        # Final Linear transformation from 64 units to 2 output units for binary classification.
        self.GwayFC = nn.Linear(64, 2)

    def forward(self, x): # computation --> Pool --> BN --> activ --> dropout
        """
        Forward pass of the network.

        Args:
            x (torch.Tensor): Input tensor.

        Returns:
            torch.Tensor: Output tensor.
        """
        x = self.b0_tcn0_ReLU(self.b0_tcn0_BN(self.b0_tcn0(x)))
        x = self.b0_tcn1_ReLU(self.b0_tcn1_BN(self.b0_conv_pool(self.b0_tcn1(x))))

        x = self.b1_tcn0_ReLU(self.b1_tcn0_BN(self.b1_tcn0(x)))
        x = self.b1_tcn1_ReLU(self.b1_tcn1_BN(self.b1_conv_pool(self.b1_tcn1(x))))

        x = self.b2_tcn0_ReLU(self.b2_tcn0_BN(self.b2_tcn0(x)))
        x = self.b2_tcn1_ReLU(self.b2_tcn1_BN(self.b2_conv_pool(self.b2_tcn1(x))))

        x = x.flatten(1)

        x = self.FC0_dropout(self.FC0_ReLU(self.FC0_BN(self.FC0(x))))
        x = self.FC1_dropout(self.FC1_ReLU(self.FC1_BN(self.FC1(x))))
        x = self.GwayFC(x)

        return x

def report_metrics(Y_test_real, prediction, metric, writer, iteration):
    """
    Calculate and print various evaluation metrics based on the predicted and actual values.
    
    Parameters:
    - Y_test_real (array-like): The actual values of the target variable.
    - prediction (array-like): The predicted values of the target variable.
    - metric (list): A list of metrics to calculate and print.
    - writer (SummaryWriter): The TensorBoard writer.
    - iteration (int): The current iteration.

    Returns:
    - float: The F1 score based on the predicted and actual values.
    """
    Y_test_real = np.asarray(Y_test_real)
    prediction = np.asarray(prediction)
    tp = np.sum((prediction == 1) & (Y_test_real == 1))
    fp = np.sum((prediction == 1) & (Y_test_real == 0))
    tn = np.sum((prediction == 0) & (Y_test_real == 0))
    fn = np.sum((prediction == 0) & (Y_test_real == 1))
    
    metrics = {
        'RMSE': lambda: np.sqrt(mean_squared_error(Y_test_real, prediction)),
        'MAE': lambda: mean_absolute_error(Y_test_real, prediction),
        'FDR': lambda: (fp / (fp + tp)) * 100 if (fp + tp) > 0 else 0,  # False Discovery Rate
        'FAR': lambda: (fp / (tn + fp)) * 100 if (tn + fp) > 0 else 0,  # False Alarm Rate
        'F1': lambda: f1_score(Y_test_real, prediction), # F1 Score
        'recall': lambda: recall_score(Y_test_real, prediction), # Recall (sensitivity)
        'precision': lambda: precision_score(Y_test_real, prediction), # Precision (positive predictive value)
        'ROC AUC': lambda: roc_auc_score(Y_test_real, prediction) # ROC AUC
    }
    for m in metric:
        if m in metrics:
            score = metrics[m]()
            print(f'SCORE {m}: %.3f' % score)
            writer.add_scalar(f'SCORE {m}', score, iteration)
    return f1_score(Y_test_real, prediction)

class LSTMTrainer:
    def __init__(self, model, optimizer, epochs, batch_size, lr):
        """
        Initialize the LSTMModelTrainer with all necessary components.

        Args:
            model (torch.nn.Module): The LSTM model to be trained and tested.
            optimizer (torch.optim.Optimizer): Optimizer used for training the model.
            epochs (int): Number of training epochs.
            batch_size (int): Batch size for training.
            lr (float): Learning rate for the optimizer.
        """
        self.model = model
        self.optimizer = optimizer
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.writer = SummaryWriter('runs/LSTM_Training_Graph')

    def FPLSTM_collate(self, batch):
        """
        Collates a batch of data for FPLSTM model.

        Args:
            batch (list): A list of tuples containing input and target tensors.

        Returns:
            tuple: A tuple containing the collated input tensor and target tensor.
        """
        xx, yy = zip(*batch)
        x_batch = torch.stack(xx).permute(1, 0, 2)
        y_batch = torch.stack(yy)
        return (x_batch, y_batch)

    def train(self, Xtrain, ytrain, epoch):
        """
        Trains the LSTM model using the given training data.

        Args:
            Xtrain (np.ndarray): The training input data.
            ytrain (np.ndarray): The training target data.
            epoch (int): The current epoch number.

        Returns:
            dict: A dictionary containing the F1 scores for different metrics.
        """
        train_loader = torch.utils.data.DataLoader(FPLSTMDataset(Xtrain, ytrain), batch_size=self.batch_size, shuffle=True, collate_fn=self.FPLSTM_collate)
        self.model.train()  # Set the model to training mode
        weights = [1.7, 0.3]  # Define class weights for the loss function, with the first class being the majority class and the second class being the minority class
        class_weights = torch.FloatTensor(weights).cuda()  # Convert class weights to a CUDA tensor
        predictions = np.zeros((Xtrain.shape[0], 2))  # Store the model's predictions
        true_labels = np.zeros(Xtrain.shape[0])  # Store the true labels
        criterion = torch.nn.CrossEntropyLoss(weight=class_weights)

        for batch_idx, data in enumerate(train_loader):
            sequences, labels = data  # Input sequences and their corresponding labels
            batchsize = sequences.shape[1]  # Number of sequences in each batch
            sequences = sequences.cuda()  # Move sequences to GPU
            labels = labels.cuda()  # Move labels to GPU
            self.optimizer.zero_grad()  # Reset gradients from previous iteration
            output = self.model(sequences)  # Forward pass through the model
            loss = criterion(output, labels)  # Calculate loss between model output and true labels
            loss.backward()  # Backward pass to calculate gradients
            self.optimizer.step()  # Update model parameters
            # Store the predicted labels for this batch in the predictions array
            predictions[(batch_idx * batchsize):((batch_idx + 1) * batchsize), :] = output.cpu().detach().numpy()
            # Store the true labels for this batch in the true_labels array
            true_labels[(batch_idx * batchsize):((batch_idx + 1) * batchsize)] = labels.cpu().numpy()

            if batch_idx > 0 and batch_idx % 10 == 0:  # Every 10 iterations, print the average loss and accuracy for the last 10 batches
                # Calculate average loss for the last 10 batches
                avg_loss = log_loss(true_labels[:((batch_idx + 1) * batchsize)], predictions[:((batch_idx + 1) * batchsize)], labels=[0, 1])
                avg_accuracy = accuracy_score(true_labels[:((batch_idx + 1) * batchsize)], predictions[:((batch_idx + 1) * batchsize)].argmax(axis=1))

                # Log to TensorBoard
                self.writer.add_scalar('Training Loss', avg_loss, epoch * len(train_loader) + batch_idx)
                self.writer.add_scalar('Training Accuracy', avg_accuracy, epoch * len(train_loader) + batch_idx)

                print('Train Epoch: {} [{}/{} ({:.0f}%)] Loss: {:.6f} Accuracy: {:.4f}'.format(
                    epoch, batch_idx * batchsize, Xtrain.shape[0], 
                    (100. * (batch_idx * batchsize) / Xtrain.shape[0]),
                    avg_loss, avg_accuracy), end="\r")

        avg_train_loss = log_loss(true_labels[:((batch_idx + 1) * batchsize)], predictions[:((batch_idx + 1) * batchsize)], labels=[0, 1])
        avg_train_acc = accuracy_score(true_labels[:((batch_idx + 1) * batchsize)], predictions[:((batch_idx + 1) * batchsize)].argmax(axis=1))

        # Log to TensorBoard
        self.writer.add_scalar('Average Training Loss', avg_train_loss, epoch)
        self.writer.add_scalar('Average Training Accuracy', avg_train_acc, epoch)

        print('Train Epoch: {} Avg Loss: {:.6f} Avg Accuracy: {}/{} ({:.0f}%)\n'.format(
            epoch, avg_train_loss, int(avg_train_acc * len(train_loader.dataset)), len(train_loader.dataset), 100. * avg_train_acc))

        true_labels = true_labels[:((batch_idx + 1) * batchsize)]
        predictions = predictions[:((batch_idx + 1) * batchsize)]
        return report_metrics(true_labels, predictions.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)

    def test(self, Xtest, ytest, epoch):
        """
        Test the LSTM model on the test dataset.

        Args:
            Xtest (np.ndarray): The input test data.
            ytest (np.ndarray): The target test data.
            epoch (int): The current epoch number.

        Returns:
            None

        """
        test_loader = torch.utils.data.DataLoader(FPLSTMDataset(Xtest, ytest), batch_size=self.batch_size, shuffle=True, collate_fn=self.FPLSTM_collate)
        self.model.eval()
        criterion = torch.nn.CrossEntropyLoss()
        test_preds = torch.as_tensor([]).cuda()
        test_labels = torch.as_tensor([], dtype=torch.long).cuda()

        with torch.no_grad():
            test_preds = torch.as_tensor([])
            test_labels = torch.as_tensor([], dtype=torch.long)
            for batch_idx, test_data in enumerate(test_loader):
                sequences, labels = test_data
                sequences = sequences.cuda()
                labels = labels.cuda()
                preds = self.model(sequences)
                loss = criterion(preds, labels)
                test_preds = torch.cat((test_preds, preds.cpu()))
                test_labels = torch.cat((test_labels, labels.cpu()))

        # Calculate metrics
        test_preds_np = test_preds.cpu().numpy()
        test_labels_np = test_labels.cpu().numpy()
        avg_test_loss = log_loss(test_labels_np, test_preds_np, labels=[0, 1])
        avg_test_acc = accuracy_score(test_labels_np, test_preds_np.argmax(axis=1))

        # Log to TensorBoard
        self.writer.add_scalar('Average Test Loss', avg_test_loss, epoch)
        self.writer.add_scalar('Average Test Accuracy', avg_test_acc, Xtest.shape[0], epoch)

        print('\nTest set: Average loss: {:.4f}, Accuracy: {:.4f}\n'.format(
            avg_test_loss, avg_test_acc))

        report_metrics(test_labels_np, test_preds_np.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)

    def run(self, Xtrain, ytrain, Xtest, ytest):
        """
        Train and validate the LSTM network.

        Args:
            Xtrain (np.ndarray): The training input data.
            ytrain (np.ndarray): The training target data.
            Xtest (np.ndarray): The testing input data.
            ytest (np.ndarray): The testing target data.

        Returns:
            None
        """
        
        # Training Loop
        F1_list = np.ndarray(5)
        i = 0
        # identical to net_train_validate but train and test are separated and train does not include test
        for epoch in range(1, self.epochs):
            F1 = self.train(Xtrain, ytrain, epoch)
            self.test(Xtest, ytest, epoch)
            F1_list[i] = F1
            i += 1
            if i == 5:
                i = 0
            if F1_list[0] != 0 and (max(F1_list) - min(F1_list)) == 0:
                print("Exited because last 5 epochs has constant F1")
            if epoch % 20 == 0:
                self.lr /= 10
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = self.lr
        self.writer.close()
        print('Training completed, saving the model...')

        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model')
        # Create the directory if it doesn't exist
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)
        # Format as string
        now_str = datetime.now.strftime("%Y%m%d_%H%M%S")
        # Save the model
        model_path = os.path.join(model_dir, f'lstm_training_epochs_{self.epochs}_batchsize_{self.batch_size}_lr_{self.lr}_{now_str}.pth')
        torch.save(self.model.state_dict(), model_path)
        print('Model saved as:', model_path)

class TCNTrainer:
    def __init__(self, model, optimizer, epochs, batch_size, lr):
        """
        Initialize the TCNTrainer with all necessary components for training and testing.

        Args:
            model (torch.nn.Module): The TCN model.
            optimizer (torch.optim.Optimizer): Optimizer used for model training.
            epochs (int): Number of training epochs.
            batch_size (int): Batch size for training.
            lr (float): Initial learning rate.
        """
        self.model = model
        self.optimizer = optimizer
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.writer = SummaryWriter('runs/TCN_Training_Graph')

    def train(self, Xtrain, ytrain, epoch):
        """
        Trains the TCN model using the given training data and parameters.

        Args:
            ep (int): The current epoch number.
            Xtrain (numpy.ndarray): The input training data.
            ytrain (numpy.ndarray): The target training data.

        Returns:
            numpy.ndarray: The F1 scores calculated using the training data.

        """
        # Randomize the order of the elements in the training set to ensure that the training process is not influenced by the order of the data
        Xtrain, ytrain = shuffle(Xtrain, ytrain)
        self.model.train()
        samples = Xtrain.shape[0]
        nbatches = samples // self.batch_size
        predictions = np.zeros((Xtrain.shape[0], 2))  # Store the model's predictions
        true_labels = np.zeros(Xtrain.shape[0])  # Store the true labels
        # we weights the different classes, the first class is the majority class, the second is the minority class
        weights = [1.7, 0.3]
        # we use the GPU to train
        class_weights = torch.FloatTensor(weights).cuda()
        # we use the CrossEntropyLoss as loss function
        criterion = torch.nn.CrossEntropyLoss(weight=class_weights)

        for batch_idx in np.arange(nbatches + 1):
            data = Xtrain[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :, :]
            target = ytrain[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]
            
            if torch.cuda.is_available():
                # Convert the data and target to tensors and move them to the GPU
                data, target = torch.Tensor(data).cuda(), torch.Tensor(target).cuda()
            else:
                # Convert the data and target to tensors
                data, target = torch.Tensor(data), torch.Tensor(target)

            # Zero the gradients since PyTorch accumulates gradients on subsequent backward passes
            self.optimizer.zero_grad()
            # Get the output predictions from the model
            output = self.model(data)
            # Calculate the loss between the predictions and the target
            loss = criterion(output, target.long())
            # Perform backpropagation to calculate the gradients of the loss with respect to the model parameters
            loss.backward()
            # Update the model parameters using the gradients and the optimizer
            self.optimizer.step()
            predictions[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :] = output.cpu().detach().numpy()
            true_labels[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)] = target.cpu().numpy()

            if batch_idx > 0 and batch_idx % 10 == 0:
                # Calculate average loss and accuracy for the last 10 batches
                avg_loss = log_loss(true_labels[:((batch_idx + 1) * self.batch_size)], predictions[:((batch_idx + 1) * self.batch_size)], labels=[0, 1])
                avg_accuracy = accuracy_score(true_labels[:((batch_idx + 1) * self.batch_size)], predictions[:((batch_idx + 1) * self.batch_size)].argmax(axis=1))

                # Log to TensorBoard
                self.writer.add_scalar('Training Loss', avg_loss, epoch * nbatches + batch_idx)
                self.writer.add_scalar('Training Accuracy', avg_accuracy, epoch * nbatches + batch_idx)

                # Print the training progress to the console
                print('Train Epoch: {} [{}/{} ({:.0f}%)] Loss: {:.6f} Accuracy: {:.4f}'.format(
                    epoch, batch_idx * self.batch_size, samples,
                    (100. * batch_idx * self.batch_size) / samples,
                    avg_loss, avg_accuracy), end="\r")

        # Calculate the average loss, accuracy, and ROC AUC over all of the batches
        avg_train_loss = log_loss(true_labels, predictions, labels=[0, 1])
        avg_train_acc = accuracy_score(true_labels, predictions.argmax(axis=1))

        # Log to TensorBoard
        self.writer.add_scalar('Average Training Loss', avg_train_loss, epoch)
        self.writer.add_scalar('Average Training Accuracy', avg_train_acc, epoch)

        print('\nTrain Epoch: {} Avg Loss: {:.6f} Avg Accuracy: {}/{} ({:.0f}%)\n'.format(
            epoch, avg_train_loss, int(avg_train_acc * samples), samples, 100. * avg_train_acc))

        return report_metrics(true_labels, predictions.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)

    def test(self, Xtest, ytest, epoch):
        """
        Test the TCN model on the test dataset.

        Args:
            Xtest (np.ndarray): Input test data.
            ytest (np.ndarray): Target test data.
            epoch (int): The current epoch number.

        Returns:
            np.ndarray: Predictions for the test set.
        """
        self.model.eval()  # Set the model to evaluation mode
        nbatches = Xtest.shape[0] // self.batch_size  # Calculate the number of batches
        predictions = np.zeros((Xtest.shape[0], 2))  # Initialize an array to store the model's predictions
        true_labels = np.zeros(Xtest.shape[0])  # Initialize an array to store the true labels
        criterion = torch.nn.CrossEntropyLoss()  # Define the loss function

        # Disable gradient calculations (since we are in test mode)
        with torch.no_grad():
            for batch_idx in np.arange(nbatches + 1):
                # Extract the data and target for this batch
                data = Xtest[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :, :]
                target = ytest[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]
                data, target = torch.Tensor(data), torch.Tensor(target)

                # If CUDA is available, move the data and target to the GPU
                if torch.cuda.is_available():
                    data, target = data.cuda(), target.cuda()

                # Forward pass: compute predicted outputs by passing inputs to the model
                output = self.model(data)

                # Store the predictions and true labels for this batch
                predictions[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :] = output.cpu().numpy()
                true_labels[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)] = target.cpu().numpy()

        # Calculate the average loss and accuracy over all of the batches
        avg_test_loss = log_loss(true_labels, predictions, labels=[0, 1])
        avg_test_acc = accuracy_score(true_labels, predictions.argmax(axis=1))

        # Log to TensorBoard
        self.writer.add_scalar('Average Test Loss', avg_test_loss, epoch)
        self.writer.add_scalar('Average Test Accuracy', avg_test_acc, epoch)

        print('\nTest set: Average loss: {:.4f}, Accuracy: {:.4f}\n'.format(
            avg_test_loss, avg_test_acc))

        report_metrics(true_labels, predictions.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)
        #return predictions.argmax(axis=1)

    def run(self, Xtrain, ytrain, Xtest, ytest):
        """
        Run the training and testing process for the model.

        Args:
            Xtrain (np.ndarray): The training input data.
            ytrain (np.ndarray): The training target data.
            Xtest (np.ndarray): The testing input data.
            ytest (np.ndarray): The testing target data.
        """
        # Use a deque to store the last 5 F1 scores to check for convergence
        F1_list = deque(maxlen=5)

        for epoch in range(1, self.epochs):
            # the train include also the test inside
            F1 = self.train(Xtrain, ytrain, epoch)
            # At each epoch, we test the network to print the accuracy
            self.test(Xtest, ytest, epoch)
            F1_list.append(F1)

            if len(F1_list) == 5 and len(set(F1_list)) == 1:
                print("Exited because last 5 epochs has constant F1")
                break

            if epoch % 20 == 0:
                self.lr /= 10
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = self.lr
        self.writer.close()
        print('Training completed, saving the model...')

        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model')
        # Create the directory if it doesn't exist
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)
        # Format as string
        now_str = datetime.now.strftime("%Y%m%d_%H%M%S")
        # Save the model
        model_path = os.path.join(model_dir, f'tcn_training_epochs_{self.epochs}_batchsize_{self.batch_size}_lr_{self.lr}_{now_str}.pth')
        torch.save(self.model.state_dict(), model_path)
        print('Model saved as:', model_path)

class MLPTrainer:
    def __init__(self, model, optimizer, epochs, batch_size, lr):
        """
        Initialize the MLPTrainer with all necessary components for training and testing.

        Args:
            model (torch.nn.Module): The MLP model.
            optimizer (torch.optim.Optimizer): Optimizer used for model training.
            epochs (int): Number of training epochs.
            batch_size (int): Batch size for training.
            lr (float): Initial learning rate.
        """
        self.model = model
        self.optimizer = optimizer
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.writer = SummaryWriter('runs/MLP_Training_Graph')

    def train(self, Xtrain, ytrain, epoch):
        """
        Trains the MLP model using the given training data and parameters.

        Args:
            epoch (int): The current epoch number.
            Xtrain (numpy.ndarray): The input training data.
            ytrain (numpy.ndarray): The target training data.

        Returns:
            numpy.ndarray: The F1 scores calculated using the training data.
        """
        Xtrain, ytrain = shuffle(Xtrain, ytrain)
        self.model.train()
        samples = Xtrain.shape[0]
        nbatches = samples // self.batch_size
        predictions = np.zeros((samples, 2))  # Store the model's predictions
        true_labels = np.zeros(samples)  # Store the true labels
        weights = [1.7, 0.3]
        class_weights = torch.FloatTensor(weights).cuda()
        criterion = torch.nn.CrossEntropyLoss(weight=class_weights)

        for batch_idx in np.arange(nbatches + 1):
            data = Xtrain[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]
            target = ytrain[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]

            if torch.cuda.is_available():
                data, target = torch.Tensor(data).cuda(), torch.Tensor(target).cuda()
            else:
                data, target = torch.Tensor(data), torch.Tensor(target)

            self.optimizer.zero_grad()
            output = self.model(data)
            loss = criterion(output, target.long())
            loss.backward()
            self.optimizer.step()
            predictions[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :] = output.cpu().detach().numpy()
            true_labels[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)] = target.cpu().numpy()

            if batch_idx > 0 and batch_idx % 10 == 0:
                avg_loss = log_loss(true_labels[:((batch_idx + 1) * self.batch_size)], predictions[:((batch_idx + 1) * self.batch_size)], labels=[0, 1])
                avg_accuracy = accuracy_score(true_labels[:((batch_idx + 1) * self.batch_size)], predictions[:((batch_idx + 1) * self.batch_size)].argmax(axis=1))
                self.writer.add_scalar('Training Loss', avg_loss, epoch * nbatches + batch_idx)
                self.writer.add_scalar('Training Accuracy', avg_accuracy, epoch * nbatches + batch_idx)
                print('Train Epoch: {} [{}/{} ({:.0f}%)] Loss: {:.6f} Accuracy: {:.4f}'.format(
                    epoch,
                    batch_idx * self.batch_size,
                    samples,
                    (100. * batch_idx * self.batch_size) / samples,
                    avg_loss,
                    avg_accuracy), end="\r")

        avg_train_loss = log_loss(true_labels, predictions, labels=[0, 1])
        avg_train_acc = accuracy_score(true_labels, predictions.argmax(axis=1))
        self.writer.add_scalar('Average Training Loss', avg_train_loss, epoch)
        self.writer.add_scalar('Average Training Accuracy', avg_train_acc, epoch)
        print('\nTrain Epoch: {} Avg Loss: {:.6f} Avg Accuracy: {}/{} ({:.0f}%)\n'.format(
            epoch, avg_train_loss, int(avg_train_acc * samples), samples, 100. * avg_train_acc))
        return report_metrics(true_labels, predictions.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)

    def test(self, Xtest, ytest, epoch):
        """
        Test the MLP model on the test dataset.

        Args:
            Xtest (np.ndarray): Input test data.
            ytest (np.ndarray): Target test data.
            epoch (int): The current epoch number.

        Returns:
            np.ndarray: Predictions for the test set.
        """
        self.model.eval()
        nbatches = Xtest.shape[0] // self.batch_size
        predictions = np.zeros((Xtest.shape[0], 2))  # Store the model's predictions
        true_labels = np.zeros(Xtest.shape[0])  # Store the true labels
        criterion = torch.nn.CrossEntropyLoss()

        with torch.no_grad():
            for batch_idx in np.arange(nbatches + 1):
                data = Xtest[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]
                target = ytest[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)]

                if torch.cuda.is_available():
                    data, target = torch.Tensor(data).cuda(), torch.Tensor(target).cuda()
                else:
                    data, target = torch.Tensor(data), torch.Tensor(target)

                output = self.model(data)
                test_loss = criterion(output, target.long()).item()
                predictions[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size), :] = output.cpu().detach().numpy()
                true_labels[(batch_idx * self.batch_size):((batch_idx + 1) * self.batch_size)] = target.cpu().numpy()

        # Calculate the average loss and accuracy over all of the batches
        avg_test_loss = log_loss(true_labels, predictions, labels=[0, 1])
        avg_test_acc = accuracy_score(true_labels, predictions.argmax(axis=1))

        # Log to TensorBoard
        self.writer.add_scalar('Average Test Loss', avg_test_loss, epoch)
        self.writer.add_scalar('Average Test Accuracy', avg_test_acc, epoch)
        print('\nTest set: Average loss: {:.4f}, Accuracy: {:.4f}\n'.format(
            avg_test_loss, avg_test_acc))

        report_metrics(true_labels, predictions.argmax(axis=1), ['FDR', 'FAR', 'F1', 'recall', 'precision', 'ROC AUC'], self.writer, epoch)
        #return predictions.argmax(axis=1)

    def run(self, Xtrain, ytrain, Xtest, ytest):
        """
        Run the training and testing process for the model.

        Args:
            Xtrain (np.ndarray): The training input data.
            ytrain (np.ndarray): The training target data.
            Xtest (np.ndarray): The testing input data.
            ytest (np.ndarray): The testing target data.
        """
        F1_list = deque(maxlen=5)
        for epoch in range(1, self.epochs):
            F1 = self.train(Xtrain, ytrain, epoch)
            self.test(Xtest, ytest, epoch)
            F1_list.append(F1)

            if len(F1_list) == 5 and len(set(F1_list)) == 1:
                print("Exited because last 5 epochs has constant F1")
                break

            if epoch % 20 == 0:
                self.lr /= 10
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = self.lr
        self.writer.close()
        print('Training completed, saving the model...')

        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'model')
        if not os.path.exists(model_dir):
            os.makedirs(model_dir)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_path = os.path.join(model_dir, f'mlp_training_epochs_{self.epochs}_batchsize_{self.batch_size}_lr_{self.lr}_{now_str}.pth')
        torch.save(self.model.state_dict(), model_path)
        print('Model saved as:', model_path)