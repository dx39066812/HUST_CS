# 指定最低CMake版本
cmake_minimum_required(VERSION 3.10)

# 指定项目名称
project(GBN)

# 设置编译器
SET(CMAKE_C_COMPILER GCC)  # 修正拼写错误
SET(CMAKE_CXX_COMPILER g++) # 添加C++编译器设置

# 设置编译选项
set(CMAKE_CXX_FLAGS "-fexec-charset=GBK")  # 修正变量名
add_definitions(-std=c++11)

# 包含目录
INCLUDE_DIRECTORIES(${PROJECT_SOURCE_DIR}/include)

# 收集源文件
aux_source_directory(${PROJECT_SOURCE_DIR}/src SRC_LIST)

# 设置输出目录
SET(EXECUTABLE_OUTPUT_PATH ${PROJECT_SOURCE_DIR}/bin)

# 创建可执行文件
ADD_EXECUTABLE(GBN ${SRC_LIST})

# 查找并链接库
FIND_LIBRARY(NETSIM_LIB libnetsim.a ${PROJECT_SOURCE_DIR}/lib)
TARGET_LINK_LIBRARIES(GBN ${NETSIM_LIB})