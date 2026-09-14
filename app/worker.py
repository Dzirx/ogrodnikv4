from rq import Worker

from app.tasks import queue

if __name__ == "__main__":
    Worker([queue], connection=queue.connection).work()
