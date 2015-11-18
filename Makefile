.PHONY: test

deps:
	sudo /usr/bin/pip install pytest amqplib

test:
	PYTHONPATH=lib/ /usr/local/bin/py.test test/

clearpyc:
	find . -name \*.pyc -delete

travis: deps test
	echo "Running travis"
