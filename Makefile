.PHONY: check lint test worker-test perimeter

# Everything CI runs, in one command.
check: lint test worker-test

lint:
	ruff check .

test:
	pytest -q

worker-test:
	node --test cloudflare-worker/test/proxy.test.mjs

# Live and opt-in: talks to production. Never part of CI. Run after every deploy.
perimeter:
	ati-lab-perimeter \
		--marker owned-domain-2026-09-26-perimeter-a \
		--other-marker owned-domain-2026-09-26-perimeter-b
