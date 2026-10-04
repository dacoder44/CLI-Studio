import subprocess
import os
import base64

from pathlib import Path
from typing import Optional
from logger import Logger

def run_command(command: str, shell: bool = True) -> Optional[str]:
    """
    Executes a system command and returns its standard output.
    
    :param command: A string (if shell=True) or a list of strings (if shell=False).
    :param shell: Set to True to invoke the system shell (allows pipes, wildcards).
    :return: The stripped string output of the command, or None if it fails.
    """
    logger = Logger("run_command")
    try:
        # capture_output=True saves stdout/stderr; text=True decodes bytes to a string
        # check=True forces a CalledProcessError if the command fails (exit code != 0)
        result = subprocess.run(
            command, 
            shell=shell, 
            capture_output=True, 
            text=True, 
            check=True
        )

        logger.log(result.stdout.strip())

        return result.stdout.strip()
        
    except subprocess.CalledProcessError as e:
        
        logger.log(f"Error: Command failed with exit code {e.returncode}")
        logger.log(f"Error Details: {e.stderr.strip()}")
        return None
        
    except FileNotFoundError:
        logger.log("Error: The specified command or executable could not be found.")
        return None

def rerun_script(script_path):
    logger = Logger("rerun_script")
    setup_()
    logger.log(f"Setup done. Rerunning script at: {script_path}")
    run_command(f'python -u {script_path}')
    logger.log(f"Ran script at: {script_path}")

def setup_():
    import os
    import sys
    import base64
    import shutil
    import subprocess
    from pathlib import Path

    logger = Logger("Setup")

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def powershell_command(script: str):
        encoded = base64.b64encode(
            script.encode("utf-16le")
        ).decode("ascii")

        return (
            f"powershell.exe -NoProfile "
            f"-EncodedCommand {encoded}"
        )

    def python_command(*args):
        python = f'"{sys.executable}"'
        return f"{python} -m {' '.join(args)}"

    def refresh_path():
        current_path = os.environ.get("PATH", "")

        windows_apps = os.path.join(
            os.environ["LOCALAPPDATA"],
            "Microsoft",
            "WindowsApps"
        )

        entries = current_path.split(";")

        if windows_apps not in entries:
            entries.append(windows_apps)

        os.environ["PATH"] = ";".join(entries)

    def has_command(command):
        refresh_path()
        return shutil.which(command) is not None

    def find_vs2022():
        """
        Finds a Visual Studio 2022 installation containing
        the x64/x86 MSVC compiler tools.
        """

        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)",
            r"C:\Program Files (x86)"
        )

        vswhere = Path(
            program_files_x86
        ) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"

        if not vswhere.exists():
            return None

        try:
            result = subprocess.run(
                [
                    str(vswhere),
                    "-latest",
                    "-products", "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-version",
                    "[17.0,18.0)",
                    "-property",
                    "installationPath"
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            path = result.stdout.strip()

            if path:
                return Path(path)

        except Exception as e:
            logger.log(
                f"Visual Studio detection failed: {e}"
            )

        return None

    # ---------------------------------------------------------
    # Python
    # ---------------------------------------------------------

    logger.log("Checking Python version...")
    run_command(
        f'"{sys.executable}" --version'
    )

    logger.log("Setting up userspace.")

    # ---------------------------------------------------------
    # WinGet
    # ---------------------------------------------------------

    if not has_command("winget"):
        logger.log(
            "Winget not found. Attempting to repair App Installer."
        )

        run_command(
            powershell_command(
                r'''
                $ErrorActionPreference = "SilentlyContinue"

                Get-Process AppInstaller `
                    -ErrorAction SilentlyContinue |
                    Stop-Process -Force

                Get-Process WinGetServer `
                    -ErrorAction SilentlyContinue |
                    Stop-Process -Force

                $package = Get-AppxPackage `
                    -Name Microsoft.DesktopAppInstaller

                if ($package) {
                    Add-AppxPackage `
                        -DisableDevelopmentMode `
                        -Register `
                        "$($package.InstallLocation)\AppXManifest.xml"
                }
                '''
            )
        )

        refresh_path()

    if not has_command("winget"):
        logger.log(
            "Winget still unavailable. Installing App Installer."
        )

        run_command(
            powershell_command(
                r'''
                $ErrorActionPreference = "Stop"

                $folder = "$env:TEMP\winget"
                $installer = "$folder\DesktopAppInstaller.msixbundle"

                New-Item `
                    -ItemType Directory `
                    -Force `
                    -Path $folder |
                    Out-Null

                Invoke-WebRequest `
                    "https://github.com/microsoft/winget-cli/releases/latest/download/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle" `
                    -OutFile $installer

                Get-Process AppInstaller `
                    -ErrorAction SilentlyContinue |
                    Stop-Process -Force

                Get-Process WinGetServer `
                    -ErrorAction SilentlyContinue |
                    Stop-Process -Force

                Add-AppxPackage `
                    -Path $installer
                '''
            )
        )

        refresh_path()

    if has_command("winget"):
        logger.log("Winget is available.")
    else:
        logger.log(
            "Winget could not be restored."
        )

    # ---------------------------------------------------------
    # CMake
    # ---------------------------------------------------------

    logger.log("Checking CMake...")

    if not has_command("cmake"):
        logger.log("Installing CMake...")

        if has_command("winget"):
            run_command(
                "winget install "
                "--id Kitware.CMake "
                "-e "
                "--accept-source-agreements "
                "--accept-package-agreements"
            )

            refresh_path()

    if has_command("cmake"):
        logger.log("CMake is available.")
    else:
        logger.log(
            "CMake is unavailable."
        )

    # ---------------------------------------------------------
    # Visual Studio 2022 Build Tools
    # ---------------------------------------------------------

    logger.log(
        "Checking Visual Studio 2022 C/C++ build tools..."
    )

    vs_path = find_vs2022()

    if vs_path is None:
        logger.log(
            "Visual Studio 2022 C++ tools not found."
        )
        logger.log(
            "Installing Visual Studio 2022 Build Tools..."
        )

        installed = False

        # WinGet installation
        if has_command("winget"):
            result = run_command(
                "winget install "
                "--id Microsoft.VisualStudio.2022.BuildTools "
                "-e "
                "--accept-source-agreements "
                "--accept-package-agreements "
                '--override "--quiet --wait --norestart '
                '--add Microsoft.VisualStudio.Workload.VCTools '
                '--includeRecommended"'
            )

            if result is not None:
                logger.log(
                    "Visual Studio installer finished."
                )

        # Check again after installation attempt.
        vs_path = find_vs2022()

        # Direct fallback if WinGet didn't produce a usable install.
        if vs_path is None:
            logger.log(
                "Visual Studio was not detected after WinGet. "
                "Using Microsoft's Build Tools installer."
            )

            run_command(
                powershell_command(
                    r'''
                    $ErrorActionPreference = "Stop"

                    $installer = "$env:TEMP\vs_buildtools.exe"

                    Invoke-WebRequest `
                        "https://aka.ms/vs/17/release/vs_buildtools.exe" `
                        -OutFile $installer

                    Start-Process `
                        -FilePath $installer `
                        -ArgumentList @(
                            "--quiet",
                            "--wait",
                            "--norestart",
                            "--add",
                            "Microsoft.VisualStudio.Workload.VCTools",
                            "--includeRecommended"
                        ) `
                        -Wait
                    '''
                )
            )

            vs_path = find_vs2022()

        if vs_path is None:
            logger.log(
                "ERROR: Visual Studio 2022 C++ Build Tools "
                "could not be detected after installation."
            )
            logger.log(
                "llama-cpp-python cannot be compiled."
            )
            return False

        logger.log(
            f"Visual Studio 2022 found: {vs_path}"
        )

    else:
        logger.log(
            f"Visual Studio 2022 found: {vs_path}"
        )

    # ---------------------------------------------------------
    # Python build tools
    # ---------------------------------------------------------

    logger.log("Updating Python build tools...")

    run_command(
        python_command(
            "pip",
            "install",
            "--upgrade",
            "pip",
            "wheel",
            "setuptools"
        )
    )

    # ---------------------------------------------------------
    # CMake configuration
    # ---------------------------------------------------------

    os.environ[
        "CMAKE_GENERATOR"
    ] = "Visual Studio 17 2022"

    os.environ[
        "CMAKE_GENERATOR_PLATFORM"
    ] = "x64"

    os.environ[
        "FORCE_CMAKE"
    ] = "1"

    logger.log(
        "Configured CMake for Visual Studio 2022 x64."
    )

    # ---------------------------------------------------------
    # Backend
    # ---------------------------------------------------------

    has_nvidia = (
        has_command("nvidia-smi")
        and has_command("nvcc")
    )

    if has_nvidia:
        logger.log(
            "NVIDIA CUDA toolchain detected."
        )

        os.environ[
            "CMAKE_ARGS"
        ] = "-DGGML_CUDA=on"

    else:
        logger.log(
            "No NVIDIA CUDA toolchain detected. "
            "Using CPU backend for now."
        )

        os.environ.pop(
            "CMAKE_ARGS",
            None
        )

    # ---------------------------------------------------------
    # llama-cpp-python
    # ---------------------------------------------------------

    logger.log(
        "Installing llama-cpp-python..."
    )

    llama_install = run_command(
        python_command(
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            "--no-cache-dir",
            "llama-cpp-python"
        )
    )

    if llama_install is None:
        logger.log(
            "ERROR: Failed to install llama-cpp-python."
        )
        return False

    logger.log(
        "llama-cpp-python installed successfully."
    )

    # ---------------------------------------------------------
    # Other Python dependencies
    # ---------------------------------------------------------

    logger.log(
        "Installing Python dependencies..."
    )

    dependencies = run_command(
        python_command(
            "pip",
            "install",
            "--upgrade",
            "psutil",
            "textual",
            "huggingface_hub"
        )
    )

    if dependencies is None:
        logger.log(
            "ERROR: Python dependency installation failed."
        )
        return False

    logger.log(
        "Installed psutil, textual, and huggingface_hub."
    )

    logger.log(
        "Set up the user successfully!"
    )

    return True