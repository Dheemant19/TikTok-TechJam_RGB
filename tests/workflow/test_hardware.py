from flowstate.training.hardware import hardware_capabilities


def test_hardware_capabilities_report_device_compatibility() -> None:
    capabilities = hardware_capabilities()

    assert isinstance(capabilities["cuda_available"], bool)
    assert isinstance(capabilities["cuda_usable"], bool)
    assert capabilities["torch_version"]
    assert capabilities["compatibility_decision"]
    if capabilities["cuda_usable"]:
        assert capabilities["torch_cuda_runtime"]
        assert capabilities["devices"]
        assert capabilities["devices"][0]["compute_capability"]
        assert capabilities["devices"][0]["memory_mb"] > 0
