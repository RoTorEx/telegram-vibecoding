UV ?= uv

.PHONY: install check lint fmt test
install:
	$(UV) sync --frozen
check: lint test
	$(UV) run --frozen mypy src
	$(UV) run --frozen telegram-vibecoding --help >/dev/null
lint:
	$(UV) run --frozen ruff check src tests scripts
	$(UV) run --frozen ruff format --check src tests scripts
test:
	PYTHONPATH=../vibecoding-core/src $(UV) run --frozen pytest -q
fmt:
	$(UV) run --frozen ruff check --fix src tests scripts
	$(UV) run --frozen ruff format src tests scripts

.PHONY: release release-push
release:
	$(UV) run --frozen python scripts/release.py
release-push:
	$(UV) run --frozen python scripts/release.py --push

.PHONY: vibe-kernel-path vibe-kernel-set vibe-pull

vibe-kernel-path:
	@test -f .vibe/KERNEL_SOURCE || { echo "Missing .vibe/KERNEL_SOURCE. Run: make vibe-kernel-set" >&2; exit 1; }
	@sed -n '1p' .vibe/KERNEL_SOURCE

vibe-kernel-set:
	@mkdir -p .vibe; \
	if [ -n "$(KERNEL)" ]; then kernel_root="$(KERNEL)"; else printf "Kernel path: "; read -r kernel_root; fi; \
	case "$$kernel_root" in /*) ;; *) echo "ERROR: kernel path must be absolute." >&2; exit 1;; esac; \
	test -f "$$kernel_root/tools/vibe-pull" || { echo "ERROR: invalid kernel path: $$kernel_root" >&2; exit 1; }; \
	printf "%s\n" "$$kernel_root" > .vibe/KERNEL_SOURCE

vibe-pull:
	@test -f .vibe/KERNEL_SOURCE || { echo "Missing .vibe/KERNEL_SOURCE. Run: make vibe-kernel-set" >&2; exit 1; }
	@kernel_root="$$(sed -n '1p' .vibe/KERNEL_SOURCE)"; \
	python3 "$$kernel_root/tools/vibe-pull" .

# VIBE:KERNEL_MAKE_START

.PHONY: vibe-propose

vibe-propose:
	@test -f .vibe/KERNEL_SOURCE || { echo "Missing .vibe/KERNEL_SOURCE. Run: make vibe-kernel-set" >&2; exit 1; }
	@kernel_root="$$(sed -n '1p' .vibe/KERNEL_SOURCE)"; \
	test -f "$$kernel_root/tools/vibe-propose" || { echo "Missing $$kernel_root/tools/vibe-propose. Update the kernel source first." >&2; exit 1; }; \
	python3 "$$kernel_root/tools/vibe-propose" .

# VIBE:KERNEL_MAKE_END
