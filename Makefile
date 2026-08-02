.PHONY: modes bootstrap quick test full build fake-root package audit

modes:
	bash scripts/restore-source-modes.sh

bootstrap:
	bash scripts/bootstrap-termux.sh

quick:
	bash scripts/test.sh --quick

test:
	bash scripts/test.sh --standard

full:
	bash scripts/test.sh --full

build:
	bash scripts/build-release.sh

fake-root:
	bash scripts/fake-magisk-root.sh

package:
	bash scripts/package-public-repo.sh

audit:
	bash scripts/public-init-audit.sh
