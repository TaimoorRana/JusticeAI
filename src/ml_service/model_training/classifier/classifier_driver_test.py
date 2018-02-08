import unittest
from model_training.classifier import classifier_driver


class TestRegressionDriver(unittest.TestCase):
    def test_failure(self):
        command_list = ['--random']
        dataset = None
        result = classifier_driver.run(command_list, dataset)
        self.assertFalse(result)
