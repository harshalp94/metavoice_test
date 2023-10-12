from abc import ABC, abstractmethod
import boto3


# An abstract class for message queues
class MessageQueue(ABC):

    @abstractmethod
    def send_message(self, message_body: str) -> None:
        pass

    @abstractmethod
    def receive_message(self) -> str:
        pass
