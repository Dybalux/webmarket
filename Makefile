.PHONY: init-env

init-env:
	cp .env.example .env
	chmod 600 .env
