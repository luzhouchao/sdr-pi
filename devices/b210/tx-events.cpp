// Experimental finite B210 source. Fixed RF settings; explicit GO; no P201 access.
#include <uhd/usrp/multi_usrp.hpp>
#include <uhd/stream.hpp>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <complex>
#include <csignal>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <poll.h>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <vector>
#include <unistd.h>

using Clock = std::chrono::steady_clock;
using Sample = std::complex<float>;
constexpr size_t FRAME = 26112, TOTAL = FRAME*321, MAX_RECORDS = 20000;
volatile std::sig_atomic_t interrupted = 0;
void stop_signal(int) { interrupted = 1; }
void check(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
long long mono_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count(); }
long long unix_ns() { return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::system_clock::now().time_since_epoch()).count(); }
std::string quote(const std::string& s) {
    std::ostringstream o; o << '"';
    for (unsigned char c : s) { if (c=='"' || c=='\\') o << '\\' << c; else if(c>=32 && c<127) o << c; else o << '?'; }
    return o.str()+'"';
}
struct SendRecord { size_t offset, requested, accepted; long long before, after; bool first; };
using Sender = std::function<size_t(size_t,size_t,bool)>;
size_t feed(const Sender& send, const std::function<bool()>& cancelled,
            std::vector<SendRecord>& records, double seconds=6,
            size_t frame_samples=FRAME, size_t total_samples=TOTAL) {
    check(frame_samples>0 && total_samples>0 && total_samples<=TOTAL, "finite frame/train samples");
    size_t offset=0, zeros=0; const auto end=Clock::now()+std::chrono::duration<double>(seconds);
    while(offset<total_samples) {
        check(!cancelled(), "TX cancelled"); check(Clock::now()<end, "TX feed deadline");
        check(records.size()<MAX_RECORDS, "send record budget");
        size_t request=std::min({size_t(1024),frame_samples-offset%frame_samples,total_samples-offset});
        auto before=mono_ns(); size_t accepted=send(offset,request,offset==0); auto after=mono_ns();
        check(accepted<=request, "invalid UHD send count");
        records.push_back({offset,request,accepted,before,after,offset==0});
        zeros=accepted==0 ? zeros+1 : 0; check(zeros<16, "no TX send progress"); offset+=accepted;
    }
    return offset;
}
void self_test() {
    std::vector<SendRecord> v;
    auto n=feed([](size_t,size_t count,bool){return count;},[]{return false;},v);
    check(n==TOTAL && v.front().first && !v.back().first,"complete feed test");
    v.clear(); bool short_once=true;
    n=feed([&](size_t,size_t count,bool){if(short_once){short_once=false;return size_t(17);}return count;},[]{return false;},v);
    check(n==TOTAL && v[1].offset==17 && !v[1].first,"partial send continuation");
    int failures=0;
    for(int test=0;test<4;test++) {
        v.clear();
        try { feed([test](size_t,size_t count,bool){return test==0 ? size_t(0) : test==1 ? count+1 : count;},
                    [test]{return test==2;},v,test==3 ? 0. : 6.); }
        catch(const std::runtime_error&) { failures++; }
    }
    check(failures==4,"zero/oversend/cancel/deadline tests");
    check(quote("a\"b\n")=="\"a\\\"b?\"","JSON escaping");
    v.clear();
    n=feed([](size_t,size_t count,bool){return std::min(count,size_t(777));},[]{return false;},v,6,17920,17920*128);
    check(n==17920*128 && v.back().offset+v.back().accepted==n,"one-pass multi-frame train");
    std::cout << "8 offline streamer tests passed; no USRP constructed\n";
}
int main(int argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="--self-test") {self_test();return 0;}
    const bool one_pass=argc==4 && std::string(argv[3])=="--stream-pilot";
    if(argc!=3 && !one_pass) {std::cerr<<"usage: tx-events PACKET_FC32 EVENTS_JSONL [--stream-pilot] (fixed2455MHz/TX60/at most4s, requires GO)\n";return 2;}
    std::ofstream log;
    std::vector<SendRecord> sends; sends.reserve(10000);
    std::vector<std::string> events; events.reserve(2000);
    std::atomic<bool> done{false}; std::atomic<bool> event_failed{false}; std::string event_error;
    uhd::tx_streamer::sptr stream; std::thread receiver;
    size_t sent=0; bool started=false; int status=1; double scheduled=0; std::string failure;
    for(auto s:{SIGINT,SIGTERM}) std::signal(s,stop_signal);
    try {
        std::ifstream input(argv[1],std::ios::binary|std::ios::ate);
        check(input.good(),"packet readable");
        const auto file_bytes=input.tellg();
        check(file_bytes>0 && file_bytes<=std::streampos(TOTAL*sizeof(Sample)) &&
              file_bytes%std::streamoff(sizeof(Sample))==0,"finite packet bytes");
        const size_t frame_samples=one_pass ? size_t(file_bytes)/sizeof(Sample) : FRAME;
        const size_t total_samples=one_pass ? frame_samples : TOTAL;
        check(file_bytes==std::streampos(frame_samples*sizeof(Sample)),"exact packet size");
        input.seekg(0); std::vector<Sample> packet(frame_samples);
        input.read(reinterpret_cast<char*>(packet.data()),frame_samples*sizeof(Sample));
        check(input.good(),"complete packet read");
        for(auto z:packet) check(std::isfinite(z.real()) && std::isfinite(z.imag()) && std::abs(z)<=.632456f,"packet peak/finite");
        // Parent checks a fresh output path and exact packet/hash before launching.
        check(access(argv[2],F_OK)!=0,"fresh event path required"); log.open(argv[2]);check(log.good(),"event log open");
        log<<std::setprecision(17);
        auto usrp=uhd::usrp::multi_usrp::make(uhd::device_addr_t("type=b200,serial=2508504"));
        usrp->set_tx_subdev_spec(uhd::usrp::subdev_spec_t("A:A"));
        usrp->set_tx_rate(2100000);usrp->set_tx_freq(uhd::tune_request_t(2455000000.,250000.));
        usrp->set_tx_gain(60);usrp->set_tx_antenna("TX/RX");usrp->set_tx_bandwidth(1500000);
        check(std::abs(usrp->get_tx_rate()-2100000)<1 && std::abs(usrp->get_tx_freq()-2455000000)<1 &&
              std::abs(usrp->get_tx_gain()-60)<.01 && std::abs(usrp->get_tx_bandwidth()-1500000)<1,"RF readback mismatch");
        check(usrp->get_tx_sensor("lo_locked").to_bool(),"TX LO unlocked");
        uhd::stream_args_t args("fc32","sc16");args.channels={0};stream=usrp->get_tx_stream(args);
        log<<"{\"kind\":\"configuration\",\"rate_sps\":"<<usrp->get_tx_rate()<<",\"frequency_hz\":"<<usrp->get_tx_freq()
           <<",\"gain_db\":"<<usrp->get_tx_gain()<<",\"bandwidth_hz\":"<<usrp->get_tx_bandwidth()
           <<",\"clock_source\":"<<quote(usrp->get_clock_source(0))<<",\"time_source\":"<<quote(usrp->get_time_source(0))
           <<",\"master_clock_hz\":"<<usrp->get_master_clock_rate()<<",\"lo_locked\":true}\n";log.flush();
        std::cout<<"{\"event\":\"ready\",\"pid\":"<<getpid()<<"}"<<std::endl;
        pollfd fd{STDIN_FILENO,POLLIN,0};check(poll(&fd,1,10000)>0,"GO deadline");char go[128];auto count=read(0,go,sizeof(go));
        check(count==3 && std::string(go,3)=="GO\n" && !interrupted,"exact GO required");
        auto query=[&](const char* name) {auto before=mono_ns();auto wall=unix_ns();auto device=usrp->get_time_now().get_real_secs();auto after=mono_ns();
            log<<"{\"kind\":\"clock_bracket\",\"phase\":"<<quote(name)<<",\"host_before_ns\":"<<before<<",\"host_after_ns\":"<<after
               <<",\"host_unix_ns\":"<<wall<<",\"device_seconds\":"<<device<<"}\n";return device;};
        scheduled=query("before_tx")+.2;
        log<<"{\"kind\":\"go\",\"host_mono_ns\":"<<mono_ns()<<",\"host_unix_ns\":"<<unix_ns()<<",\"scheduled_device_seconds\":"<<scheduled<<"}\n";log.flush();
        receiver=std::thread([&] {
            try {
                while(!done) {
                    uhd::async_metadata_t m{};
                    if(!stream->recv_async_msg(m,.02)) continue;
                    check(events.size()<MAX_RECORDS,"async record budget");
                    std::ostringstream o;o<<std::setprecision(17)<<"{\"kind\":\"async\",\"host_receive_mono_ns\":"<<mono_ns()
                     <<",\"host_receive_unix_ns\":"<<unix_ns()<<",\"channel\":"<<m.channel<<",\"event_code\":"<<int(m.event_code)
                     <<",\"has_device_time\":"<<(m.has_time_spec?"true":"false")<<",\"device_seconds\":";
                    if(m.has_time_spec)o<<m.time_spec.get_real_secs();else o<<"null";
                    o<<",\"user_payload\":["<<m.user_payload[0]<<','<<m.user_payload[1]<<','<<m.user_payload[2]<<','<<m.user_payload[3]<<"]}";
                    events.push_back(o.str());
                }
            } catch(const std::exception& e){event_error=e.what();event_failed=true;}
        });
        std::cout<<"{\"event\":\"tx_start\",\"scheduled_device_seconds\":"<<std::setprecision(17)<<scheduled<<"}"<<std::endl;
        started=true;
        sent=feed([&](size_t offset,size_t count,bool first){uhd::tx_metadata_t m;m.start_of_burst=first;m.end_of_burst=false;m.has_time_spec=first;m.time_spec=uhd::time_spec_t(scheduled);
            return stream->send(&packet[offset%frame_samples],count,m,.25);},[&]{return interrupted || event_failed;},sends,6,frame_samples,total_samples);
        uhd::tx_metadata_t end;end.end_of_burst=true;Sample empty{};stream->send(&empty,0,end,.25);started=false;
        auto deadline=Clock::now()+std::chrono::milliseconds(1000);
        while(Clock::now()<deadline && !interrupted && !event_failed)std::this_thread::sleep_for(std::chrono::milliseconds(10));
        check(!interrupted && !event_failed,"async drain interrupted/failed");query("after_tx");status=0;
    } catch(const std::exception& e) {failure=e.what();}
    if(started && stream) {try {uhd::tx_metadata_t m;m.end_of_burst=true;Sample empty{};stream->send(&empty,0,m,.25);}catch(...) {}}
    done=true;if(receiver.joinable())receiver.join();
    if(event_failed){status=1;failure+=" async: "+event_error;}
    sent=0;for(const auto& r:sends)sent+=r.accepted;
    for(const auto& r:sends) log<<"{\"kind\":\"send\",\"offset_samples\":"<<r.offset<<",\"requested\":"<<r.requested<<",\"accepted\":"<<r.accepted
        <<",\"host_before_ns\":"<<r.before<<",\"host_after_ns\":"<<r.after<<",\"start_of_burst\":"<<(r.first?"true":"false")<<"}\n";
    for(const auto& e:events)log<<e<<'\n';
    log<<"{\"kind\":\"summary\",\"status\":"<<quote(status==0?"sent_complete":"failed")<<",\"accepted_samples\":"<<sent
       <<",\"send_records\":"<<sends.size()<<",\"async_records\":"<<events.size()<<",\"error\":"<<quote(failure)<<"}\n";log.close();
    if(status)std::cerr<<failure<<'\n';
    return status;
}
