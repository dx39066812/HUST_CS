# 指定最低CMake版本
cmake_minimum_required(VERSION 3.10)

# 指定项目名称
project(SR)

# 设置编译器
SET(CMAKE_C_COMPILER GCC)  # 修正拼写错误
SET(CMAKE_CXX_COMPILER g++) # 添加C++编译器设置

# 包含目录
INCLUDE_DIRECTORIES(${PROJECT_SOURCE_DIR}/include)

# 收集源文件
aux_source_directory(${PROJECT_SOURCE_DIR}/src SRC_LIST)

# 设置输出目录
SET(EXECUTABLE_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/bin)

# 创建可执行文件
ADD_EXECUTABLE(SR ${SRC_LIST})

#使用GDB调试
target_compile_options(SR PRIVATE -g)

# 查找并链接库
FIND_LIBRARY(NETSIM_LIB libnetsim.a ${PROJECT_SOURCE_DIR}/lib)
TARGET_LINK_LIBRARIES(SR ${NETSIM_LIB})