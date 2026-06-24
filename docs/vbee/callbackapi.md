# Callback API

Khi request thành công, hệ thống VBEE TTS sẽ gửi đến Callback URL một HTTP POST như sau

**URL**: callback url truyền lên khi gọi API Create speech

**Method**: POST

**Body**:

<table data-header-hidden><thead><tr><th width="177"></th><th width="165"></th><th></th></tr></thead><tbody><tr><td>Thuộc tính</td><td>Kiểu dữ liệu</td><td>Mô tả</td></tr><tr><td>app_id</td><td>String</td><td>ID của ứng dụng</td></tr><tr><td>request_id</td><td>String</td><td>ID của request</td></tr><tr><td>characters</td><td>Number</td><td>Số ký tự của đoạn văn bản</td></tr><tr><td>voice_code</td><td>String</td><td>Mã giọng</td></tr><tr><td>audio_type</td><td>String</td><td>Định dạng tệp audio đầu ra</td></tr><tr><td>speed_rate</td><td>Number</td><td>Tốc độ đọc</td></tr><tr><td>sample_rate</td><td>String</td><td>Sample rate của audio đầu ra</td></tr><tr><td>bitrate</td><td>Number</td><td>Bitrate của tệp audio đầu ra</td></tr><tr><td>created_at</td><td>String</td><td>Thời gian khởi tạo request</td></tr><tr><td>status</td><td>String</td><td><p>Trạng thái của request</p><p>* SUCCESS: Thành công</p><p>* FAILURE: Thất bại</p></td></tr><tr><td>audio_link</td><td>String</td><td>Đường dẫn tải tệp audio tổng hợp</td></tr></tbody></table>

```
//Example request
{
    "app_id": "{{app_id}}",
    "response_type": "indirect",
    "callback_url": "https://mydomain/callback",
    "input_text": "Xin Chào mừng đén với website của chúng tôi! Đây là trang web cung cấp một giải pháp văn bản thành giọng nói, trên cơ sở, nó hỗ trợ các doanh nghiệp xây dựng các hệ thống trung tâm cuộc gọi tự động, hệ thống thông báo công khai, trợ lý ảo, tin tức âm thanh, podcast, sách âm thanh và tường thuật phim.",
    "voice_code": "hn_female_ngochuyen_full_48k-fhg",
    "audio_type":"mp3",
    "bitrate": 128,
    "speed_rate": "1.0"
}

```
