from dataclasses import dataclass

import psutil

_nvml_available = False
_nvml_handle = None
_pynvml = None

_wmi_available = False
_wmi_conn = None


def _init_nvml():
    global _nvml_available, _nvml_handle, _pynvml
    try:
        import pynvml
        _pynvml = pynvml
        _pynvml.nvmlInit()
        _nvml_handle = _pynvml.nvmlDeviceGetHandleByIndex(0)
        _nvml_available = True
    except Exception:
        _nvml_available = False


def _init_wmi():
    global _wmi_available, _wmi_conn
    try:
        import wmi
        _wmi_conn = wmi.WMI(namespace="root\\wmi")
        _wmi_available = True
    except Exception:
        _wmi_available = False


_init_nvml()
_init_wmi()


@dataclass(slots=True)
class HWStatus:
    cpu_percent: float = 0.0
    gpu_percent: float = -1.0
    mem_percent: float = 0.0
    cpu_temp: int = -1
    gpu_temp: int = -1


def _get_cpu_temp() -> int:
    if not _wmi_available:
        return -1
    try:
        sensors = _wmi_conn.MSAcpi_ThermalZoneTemperature()
        if sensors:
            return int(sensors[0].CurrentTemperature / 10 - 273.15)
    except Exception:
        pass
    return -1


def _get_gpu_usage() -> float:
    if not _nvml_available:
        return -1.0
    try:
        return float(_pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle).gpu)
    except Exception:
        return -1.0


def _get_gpu_temp() -> int:
    if not _nvml_available:
        return -1
    try:
        return _pynvml.nvmlDeviceGetTemperature(
            _nvml_handle, _pynvml.NVML_TEMPERATURE_GPU
        )
    except Exception:
        return -1


def collect() -> HWStatus:
    return HWStatus(
        cpu_percent=psutil.cpu_percent(interval=0),
        gpu_percent=_get_gpu_usage(),
        mem_percent=psutil.virtual_memory().percent,
        cpu_temp=_get_cpu_temp(),
        gpu_temp=_get_gpu_temp(),
    )
