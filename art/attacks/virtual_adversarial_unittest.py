# MIT License
#
# Copyright (C) IBM Corporation 2018
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
from __future__ import absolute_import, division, print_function, unicode_literals

import unittest

import keras
import keras.backend as k
from keras.models import Sequential
from keras.layers import Dense, Flatten, Conv2D, MaxPooling2D
import numpy as np
import tensorflow as tf
import torch.nn as nn
import torch.optim as optim

from art.attacks.virtual_adversarial import VirtualAdversarialMethod
from art.classifiers import KerasClassifier, PyTorchClassifier, TFClassifier
from art.utils import load_mnist, get_labels_np_array

BATCH_SIZE = 10
NB_TRAIN = 100
NB_TEST = 10


class Model(nn.Module):
    def __init__(self):
        super(Model, self).__init__()
        self.conv = nn.Conv2d(1, 16, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.fc = nn.Linear(2304, 10)

    def forward(self, x):
        import torch.nn.functional as f

        x = self.pool(f.relu(self.conv(x)))
        x = x.view(-1, 2304)
        logit_output = self.fc(x)

        return logit_output


class TestVirtualAdversarial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        k.set_learning_phase(1)

        # Get MNIST
        (x_train, y_train), (x_test, y_test), _, _ = load_mnist()
        x_train, y_train, x_test, y_test = x_train[:NB_TRAIN], y_train[:NB_TRAIN], x_test[:NB_TEST], y_test[:NB_TEST]
        cls.mnist = (x_train, y_train), (x_test, y_test)

        # Keras classifier
        cls.classifier_k = cls._cnn_mnist_k([28, 28, 1])
        cls.classifier_k.fit(x_train, y_train, batch_size=BATCH_SIZE, nb_epochs=2)

        scores = cls.classifier_k._model.evaluate(x_train, y_train)
        print("\n[Keras, MNIST] Accuracy on training set: %.2f%%" % (scores[1] * 100))
        scores = cls.classifier_k._model.evaluate(x_test, y_test)
        print("\n[Keras, MNIST] Accuracy on test set: %.2f%%" % (scores[1] * 100))

        # Create basic CNN on MNIST using TensorFlow
        cls.classifier_tf = cls._cnn_mnist_tf([28, 28, 1])
        cls.classifier_tf.fit(x_train, y_train, nb_epochs=2, batch_size=BATCH_SIZE)

        scores = get_labels_np_array(cls.classifier_tf.predict(x_train))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_train, axis=1)) / y_train.shape[0]
        print('\n[TF, MNIST] Accuracy on training set: %.2f%%' % (acc * 100))

        scores = get_labels_np_array(cls.classifier_tf.predict(x_test))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\n[TF, MNIST] Accuracy on test set: %.2f%%' % (acc * 100))

        # Create basic PyTorch model
        cls.classifier_py = cls._cnn_mnist_py()
        x_train, x_test = np.swapaxes(x_train, 1, 3), np.swapaxes(x_test, 1, 3)
        cls.classifier_py.fit(x_train, y_train, nb_epochs=2, batch_size=BATCH_SIZE)

        scores = get_labels_np_array(cls.classifier_py.predict(x_train))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_train, axis=1)) / y_train.shape[0]
        print('\n[PyTorch, MNIST] Accuracy on training set: %.2f%%' % (acc * 100))

        scores = get_labels_np_array(cls.classifier_py.predict(x_test))
        acc = np.sum(np.argmax(scores, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\n[PyTorch, MNIST] Accuracy on test set: %.2f%%' % (acc * 100))

    def test_mnist(self):
        # Define all backends to test
        backends = {'keras': self.classifier_k,
                    'tf': self.classifier_tf,
                    'pytorch': self.classifier_py}

        for _, classifier in backends.items():
            if _ == 'pytorch':
                self._swap_axes()
            self._test_backend_mnist(classifier)
            if _ == 'pytorch':
                self._swap_axes()

    def _swap_axes(self):
        (x_train, y_train), (x_test, y_test) = self.mnist
        x_train = np.swapaxes(x_train, 1, 3)
        x_test = np.swapaxes(x_test, 1, 3)
        self.mnist = (x_train, y_train), (x_test, y_test)

    def _test_backend_mnist(self, classifier):
        # Get MNIST
        (_, _), (x_test, y_test) = self.mnist
        x_test, y_test = x_test[:NB_TEST], y_test[:NB_TEST]

        df = VirtualAdversarialMethod(classifier)
        x_test_adv = df.generate(x_test, eps=1)
        self.assertFalse((x_test == x_test_adv).all())

        y_pred = get_labels_np_array(classifier.predict(x_test_adv))
        self.assertFalse((y_test == y_pred).all())

        acc = np.sum(np.argmax(y_pred, axis=1) == np.argmax(y_test, axis=1)) / y_test.shape[0]
        print('\nAccuracy on adversarial examples: %.2f%%' % (acc * 100))

    @staticmethod
    def _cnn_mnist_tf(input_shape):
        labels_tf = tf.placeholder(tf.float32, [None, 10])
        inputs_tf = tf.placeholder(tf.float32, [None] + list(input_shape))

        # Define the tensorflow graph
        conv = tf.layers.conv2d(inputs_tf, 4, 5, activation=tf.nn.relu)
        conv = tf.layers.max_pooling2d(conv, 2, 2)
        fc = tf.contrib.layers.flatten(conv)

        # Logits layer
        logits = tf.layers.dense(fc, 10)

        # Train operator
        loss = tf.reduce_mean(tf.losses.softmax_cross_entropy(logits=logits, onehot_labels=labels_tf))
        optimizer = tf.train.AdamOptimizer(learning_rate=0.01)
        train_tf = optimizer.minimize(loss)

        sess = tf.Session()
        sess.run(tf.global_variables_initializer())

        classifier = TFClassifier((0, 1), inputs_tf, logits, loss=loss, train=train_tf, output_ph=labels_tf, sess=sess)
        return classifier

    @staticmethod
    def _cnn_mnist_k(input_shape):
        # Create simple CNN
        model = Sequential()
        model.add(Conv2D(4, kernel_size=(5, 5), activation='relu', input_shape=input_shape))
        model.add(MaxPooling2D(pool_size=(2, 2)))
        model.add(Flatten())
        model.add(Dense(10, activation='softmax'))

        model.compile(loss=keras.losses.categorical_crossentropy, optimizer=keras.optimizers.Adam(lr=0.01),
                      metrics=['accuracy'])

        classifier = KerasClassifier((0, 1), model, use_logits=False)
        return classifier

    @staticmethod
    def _cnn_mnist_py():
        model = Model()

        # Define a loss function and optimizer
        loss_fn = nn.CrossEntropyLoss()
        optimizer = optim.Adam(model.parameters(), lr=0.01)

        # Get classifier
        classifier = PyTorchClassifier((0, 1), model, loss_fn, optimizer, (1, 28, 28), 10)
        return classifier


if __name__ == '__main__':
    unittest.main()
