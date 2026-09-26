// Simple HTTP Server
// Requirements: C++17 + Winsock2
// Compile: g++ -std=c++17 server.cpp -o server.exe -lws2_32
// Run:     ./server.exe 127.0.0.1 8080 ./wwwroot

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <winsock2.h>
#include <ws2tcpip.h>

#pragma comment(lib, "ws2_32.lib")

using namespace std;
namespace fs = std::filesystem;

// ---------- Helper Functions ----------

// get current time string
string now_str()
{
    auto t = chrono::system_clock::to_time_t(chrono::system_clock::now());
    char buf[64];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", localtime(&t));
    return string(buf);
}

// percent-decode URL
string url_decode(const string &s)
{
    string out;
    for (size_t i = 0; i < s.size(); ++i)
    {
        if (s[i] == '%' && i + 2 < s.size())
        {
            string hex = s.substr(i + 1, 2);
            char ch = (char)strtol(hex.c_str(), nullptr, 16);
            out += ch;
            i += 2;
        }
        else if (s[i] == '+')
        {
            out += ' ';
        }
        else
        {
            out += s[i];
        }
    }
    return out;
}

// guess MIME type based on file extension
string mime_type(const fs::path &path)
{
    static unordered_map<string, string> mime = {
        {".html", "text/html"}, {".htm", "text/html"}, {".jpg", "image/jpeg"}, {".jpeg", "image/jpeg"}, {".png", "image/png"}, {".gif", "image/gif"}, {".css", "text/css"}, {".js", "application/javascript"}, {".txt", "text/plain"}, {".json", "application/json"}};
    string ext = path.extension().string();
    for (auto &c : ext)
        c = tolower(c);
    return mime.count(ext) ? mime[ext] : "application/octet-stream";
}

// reliable send (handle partial send)
bool send_all(SOCKET sock, const char *data, size_t len)
{
    size_t sent = 0;
    while (sent < len)
    {
        int n = send(sock, data + sent, (int)(len - sent), 0);
        if (n <= 0)
            return false;
        sent += n;
    }
    return true;
}

// read until header end (\r\n\r\n)
string recv_request(SOCKET client)
{
    string req;
    char buf[1024];
    while (true)
    {
        int n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0)
            break;
        req.append(buf, buf + n);
        if (req.find("\r\n\r\n") != string::npos)
            break;
        if (req.size() > 16 * 1024)
            break; // max header 16KB
    }
    return req;
}

// send basic error response
void send_error(SOCKET client, int code, const string &msg)
{
    ostringstream oss;
    string body = "<h1>" + to_string(code) + " " + msg + "</h1>";
    oss << "HTTP/1.1 " << code << " " << msg << "\r\n"
        << "Content-Type: text/html\r\n"
        << "Content-Length: " << body.size() << "\r\n"
        << "Connection: close\r\n\r\n"
        << body;
    string resp = oss.str();
    send_all(client, resp.c_str(), resp.size());
}

// ---------- Main HTTP Handling ----------

void handle_client(SOCKET client, const fs::path &root, const string &client_ip, int client_port)
{
    string request = recv_request(client);
    if (request.empty())
    {
        closesocket(client);
        return;
    }

    istringstream iss(request);
    string method, url, version;
    iss >> method >> url >> version;

    cout << now_str() << " [" << client_ip << ":" << client_port << "] "
         << method << " " << url << " ";

    if (method != "GET")
    {
        send_error(client, 405, "Method Not Allowed");
        cout << "-> 405" << endl;
        closesocket(client);
        return;
    }

    // decode URL and prevent directory traversal
    string path_decoded = url_decode(url);
    if (path_decoded.find("..") != string::npos)
    {
        send_error(client, 403, "Forbidden");
        cout << "-> 403" << endl;
        closesocket(client);
        return;
    }

    if (path_decoded == "/")
        path_decoded = "/index.html";
    fs::path file_path = root / fs::path(path_decoded.substr(1));

    if (!fs::exists(file_path) || fs::is_directory(file_path))
    {
        send_error(client, 404, "Not Found");
        cout << "-> 404" << endl;
        closesocket(client);
        return;
    }

    ifstream file(file_path, ios::binary);
    if (!file)
    {
        send_error(client, 500, "Internal Server Error");
        cout << "-> 500" << endl;
        closesocket(client);
        return;
    }

    // get file size
    file.seekg(0, ios::end);
    size_t size = (size_t)file.tellg();
    file.seekg(0, ios::beg);

    // send headers
    ostringstream header;
    header << "HTTP/1.1 200 OK\r\n"
           << "Content-Type: " << mime_type(file_path) << "\r\n"
           << "Content-Length: " << size << "\r\n"
           << "Connection: close\r\n\r\n";
    string h = header.str();
    send_all(client, h.c_str(), h.size());

    // send file content
    vector<char> buffer(8192);
    while (file)
    {
        file.read(buffer.data(), buffer.size());
        streamsize bytes = file.gcount();
        if (bytes > 0)
        {
            if (!send_all(client, buffer.data(), bytes))
                break;
        }
    }

    cout << "-> 200 OK (" << size << " bytes)" << endl;
    closesocket(client);
}

// ---------- Entry Point ----------

int main(int argc, char *argv[])
{
    if (argc < 4)
    {
        cerr << "Usage: server.exe <ip> <port> <wwwroot>\n";
        cerr << "Example: server.exe 0.0.0.0 8080 ./wwwroot\n";
        return 1;
    }

    string ip = argv[1];
    int port = stoi(argv[2]);
    fs::path wwwroot = argv[3];
    if (!fs::exists(wwwroot) || !fs::is_directory(wwwroot))
    {
        cerr << "Error: wwwroot is invalid.\n";
        return 1;
    }

    // Initialize Winsock
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
    {
        cerr << "WSAStartup failed.\n";
        return 1;
    }

    SOCKET server_fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (server_fd == INVALID_SOCKET)
    {
        cerr << "socket() failed.\n";
        WSACleanup();
        return 1;
    }

    sockaddr_in server_addr{};
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(port);

    if (inet_pton(AF_INET, ip.c_str(), &server_addr.sin_addr) <= 0)
    {
        cerr << "Invalid IP address: " << ip << endl;
        closesocket(server_fd);
        WSACleanup();
        return 1;
    }

    if (bind(server_fd, (sockaddr *)&server_addr, sizeof(server_addr)) == SOCKET_ERROR)
    {
        cerr << "bind() failed. Maybe port in use.\n";
        closesocket(server_fd);
        WSACleanup();
        return 1;
    }

    if (listen(server_fd, 5) == SOCKET_ERROR)
    {
        cerr << "listen() failed.\n";
        closesocket(server_fd);
        WSACleanup();
        return 1;
    }

    cout << now_str() << "  Server started on " << ip << ":" << port
         << " (root: " << wwwroot << ")" << endl;

    // Accept loop
    while (true)
    {
        sockaddr_in client_addr{};
        int len = sizeof(client_addr);
        SOCKET client = accept(server_fd, (sockaddr *)&client_addr, &len);
        if (client == INVALID_SOCKET)
        {
            cerr << "accept() failed.\n";
            continue;
        }

        char client_ip[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &client_addr.sin_addr, client_ip, sizeof(client_ip));
        int client_port = ntohs(client_addr.sin_port);

        handle_client(client, wwwroot, client_ip, client_port);
    }

    closesocket(server_fd);
    WSACleanup();
    return 0;
}
