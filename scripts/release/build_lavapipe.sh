#!/bin/sh
# Mesa's lavapipe, Vulkan on the CPU, for the Linux wheels: the engine draws with it on a machine
# with no GPU driver (rust/engine/src/lavapipe.rs). cibuildwheel runs this in the manylinux
# image before it builds a wheel (`sh scripts/release/build_lavapipe.sh DIRECTORY`, the package's
# manimgx/lavapipe, beside the engine): Mesa from its source (and glslang, which compiles some of
# lavapipe's shaders as Mesa builds), with the image's LLVM linked in, into
# DIRECTORY/libvulkan_lvp.so.
set -eu

mesa=26.2.3
mesa_sha256=1628058a8d2c0615975de5a15ab7bbb9638c50000b5bed9456ff423ea034a81f
glslang=16.6.0
glslang_sha256=9c09b901149c729df745057dafa815278aaa101b84d2b6e14f16a42de52f97f2

mkdir -p "$1"
out=$(cd "$1" && pwd)
work=$(mktemp -d)
# libxml2: the image's LLVM lists it among its system libraries
dnf -q -y install llvm-devel llvm-static libxml2-devel
python=/opt/python/cp313-cp313/bin/python
"$python" -m pip -q install --root-user-action=ignore meson ninja mako pyyaml cmake
export PATH="$work/bin:/opt/python/cp313-cp313/bin:$PATH"
cd "$work"

curl -sSfL -o glslang.tar.gz "https://github.com/KhronosGroup/glslang/archive/refs/tags/$glslang.tar.gz"
echo "$glslang_sha256  glslang.tar.gz" | sha256sum -c --quiet
tar -xzf glslang.tar.gz
cmake -S "glslang-$glslang" -B glslang-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$work" \
  -DENABLE_OPT=OFF -DENABLE_HLSL=OFF -DGLSLANG_TESTS=OFF -DBUILD_EXTERNAL=OFF -DENABLE_GLSLANG_JS=OFF
ninja -C glslang-build install

curl -sSfL -o mesa.tar.xz "https://archive.mesa3d.org/mesa-$mesa.tar.xz"
echo "$mesa_sha256  mesa.tar.xz" | sha256sum -c --quiet
tar -xJf mesa.tar.xz
# lavapipe alone, for no window system, with no disk cache; exporting the loader's interface alone
# (Mesa's src/vulkan/vulkan-icd-symbols.txt), not the LLVM linked in
echo '{ global: vk_icdGetInstanceProcAddr; vk_icdGetPhysicalDeviceProcAddr; vk_icdNegotiateLoaderICDInterfaceVersion; local: *; };' > lvp.map
meson setup mesa-build "mesa-$mesa" --buildtype=release -Db_ndebug=true \
  -Dc_args="-ffunction-sections -fdata-sections" -Dcpp_args="-ffunction-sections -fdata-sections" \
  -Dc_link_args="-Wl,--version-script=$work/lvp.map" -Dcpp_link_args="-Wl,--version-script=$work/lvp.map" \
  -Dplatforms= -Dvulkan-drivers=swrast -Dgallium-drivers= -Dopengl=false -Dglx=disabled -Degl=disabled \
  -Dgbm=disabled -Dgles1=disabled -Dgles2=disabled -Dglvnd=disabled -Dllvm=enabled -Dshared-llvm=disabled \
  -Dshader-cache=disabled -Dzlib=disabled -Dzstd=disabled -Dexpat=disabled -Dxmlconfig=disabled \
  -Dvalgrind=disabled -Dlibunwind=disabled -Dlmsensors=disabled -Dvideo-codecs= -Dmicrosoft-clc=disabled \
  -Dspirv-tools=disabled -Dintel-rt=disabled -Dgallium-va=disabled
ninja -C mesa-build src/gallium/targets/lavapipe/libvulkan_lvp.so
strip --strip-unneeded -o "$out/libvulkan_lvp.so" mesa-build/src/gallium/targets/lavapipe/libvulkan_lvp.so
rm -rf "$work"
