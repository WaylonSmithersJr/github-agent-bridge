from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "release.yml"


def release_steps():
    sections = WORKFLOW.read_text().split("\n      - name: ")[1:]
    return {
        name: body
        for section in sections
        for name, _, body in [section.partition("\n")]
    }


def test_release_checkout_can_pin_an_older_workflow_sha():
    steps = release_steps()

    checkout = steps["Checkout workflow SHA"]
    assert "ref: ${{ github.sha }}" in checkout
    assert "fetch-depth: 0" in checkout
    assert 'git checkout -B "$GITHUB_REF_NAME" "$GITHUB_SHA"' in steps[
        "Restore release branch at workflow SHA"
    ]


def test_stale_release_runs_skip_validation_and_publish_steps():
    steps = release_steps()
    initial_guard = steps["Check workflow SHA is still current"]

    assert "id: release_head" in initial_guard
    assert 'refs/heads/${GITHUB_REF_NAME}' in initial_guard
    assert 'echo "current=false" >> "$GITHUB_OUTPUT"' in initial_guard

    guarded_steps = [
        "Set up Python",
        "Set up Node",
        "Install package with test dependencies",
        "Install dashboard dependencies",
        "Run dashboard tests",
        "Build dashboard",
        "Run tests before release",
        "Recheck workflow SHA before release",
    ]
    for name in guarded_steps:
        assert "if: steps.release_head.outputs.current == 'true'" in steps[name]

    final_guard = steps["Recheck workflow SHA before release"]
    assert "id: pre_release_head" in final_guard
    assert 'refs/heads/${GITHUB_REF_NAME}' in final_guard
    assert "if: steps.pre_release_head.outputs.current == 'true'" in steps[
        "Semantic version release"
    ]
